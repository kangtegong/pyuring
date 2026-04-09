#!/usr/bin/env python3
"""
asyncio file server using UringAsync.

A common pattern in async web frameworks (aiohttp, Starlette, FastAPI) is to
serve static files: open a file, read its contents, and stream the bytes to
a network socket. The standard approach uses aiofiles or loop.run_in_executor
to avoid blocking the event loop on file reads.

pyuring provides a third option: use UringAsync to submit file reads as io_uring
SQEs and await completions via the ring's CQ file descriptor. The event loop
monitors ring_fd with add_reader(), so there is no extra thread pool and no
per-operation thread wakeup overhead.

This example implements a minimal asyncio TCP server that:
  1. Accepts a connection
  2. Reads a filename from the client (one line)
  3. Reads the file using UringAsync
  4. Sends the file contents back
  5. Closes the connection

It demonstrates UringAsync in a realistic concurrent I/O context alongside
asyncio network sockets.

Usage:
    # Terminal 1: start the server
    python3 examples/async_file_server.py --serve

    # Terminal 2: request a file
    echo "/etc/hostname" | nc 127.0.0.1 9999

    # Run the built-in self-test (starts server, sends requests, checks output)
    python3 examples/async_file_server.py
    python3 examples/async_file_server.py --files 20 --size-kb 64
"""

from __future__ import annotations

import asyncio
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyuring as iou
from pyuring import UringAsync, UringCtx, UringError

HOST = "127.0.0.1"
PORT = 9999


async def read_file_with_uring(path: str, ctx: UringCtx, ua: UringAsync) -> bytes:
    """
    Read a file asynchronously using UringAsync.

    Submits read SQEs for each block of the file, then awaits completions
    via the event loop reader registered on ctx.ring_fd. The event loop
    is not blocked between submission and completion.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as e:
        raise FileNotFoundError(f"cannot open {path}: {e}") from e

    try:
        file_size = os.fstat(fd).st_size
        if file_size == 0:
            return b""

        block_size = min(file_size, 64 * 1024)  # 64 KiB blocks
        blocks = (file_size + block_size - 1) // block_size
        buffers = [bytearray(block_size) for _ in range(blocks)]

        # Submit all read SQEs
        for i, buf in enumerate(buffers):
            offset = i * block_size
            read_len = min(block_size, file_size - offset)
            # Resize buffer to actual read length for the last block
            if read_len < block_size:
                buffers[i] = bytearray(read_len)
            ctx.read_async(fd, buffers[i], offset=offset, user_data=i)
        ctx.submit()

        # Collect completions; UringAsync delivers them via event loop reader
        results = {}
        for _ in range(blocks):
            user_data, n_bytes = await ua.wait_completion()
            if n_bytes < 0:
                raise UringError(-n_bytes, "read_file_async")
            results[user_data] = n_bytes

        # Reassemble in order
        chunks = []
        for i in range(blocks):
            n = results[i]
            chunks.append(bytes(buffers[i][:n]))
        return b"".join(chunks)

    finally:
        os.close(fd)


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                        ctx: UringCtx, ua: UringAsync) -> None:
    peer = writer.get_extra_info("peername")
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        path = line.decode().strip()
        if not path:
            writer.write(b"ERROR: empty path\n")
            return

        try:
            data = await read_file_with_uring(path, ctx, ua)
            writer.write(data)
        except FileNotFoundError as e:
            writer.write(f"ERROR: {e}\n".encode())
        except UringError as e:
            writer.write(f"ERROR: io_uring: {e}\n".encode())

        await writer.drain()
    except asyncio.TimeoutError:
        writer.write(b"ERROR: timeout\n")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def run_server(stop_event: asyncio.Event) -> None:
    """Run the file server until stop_event is set."""
    # One UringCtx + UringAsync pair shared across all connections.
    # This is safe as long as connections are handled on the same event loop thread.
    ctx = iou.UringCtx(entries=256)
    ua = UringAsync(ctx)

    async def client_handler(reader, writer):
        await handle_client(reader, writer, ctx, ua)

    server = await asyncio.start_server(client_handler, HOST, PORT)
    async with server:
        await stop_event.wait()

    ua.close()
    ctx.close()


async def self_test(num_files: int, size_kb: int) -> None:
    """Create test files, start the server, send requests, verify responses."""
    with tempfile.TemporaryDirectory(prefix="pyuring_srv_") as tmpdir:
        # Create test files
        files = []
        for i in range(num_files):
            path = os.path.join(tmpdir, f"file_{i:04d}.bin")
            content = bytes([i & 0xFF]) * (size_kb * 1024)
            with open(path, "wb") as f:
                f.write(content)
            files.append((path, content))

        stop_event = asyncio.Event()
        server_task = asyncio.create_task(run_server(stop_event))

        # Give the server a moment to bind
        await asyncio.sleep(0.1)

        print(f"Server started on {HOST}:{PORT}")
        print(f"Requesting {num_files} files × {size_kb} KiB each...")
        print()

        t0 = time.perf_counter()
        errors = 0

        for path, expected in files:
            r, w = await asyncio.open_connection(HOST, PORT)
            w.write((path + "\n").encode())
            await w.drain()
            # read(n) returns at most n bytes; loop until EOF to get the full file
            chunks = []
            while True:
                chunk = await r.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            received = b"".join(chunks)
            w.close()
            await w.wait_closed()

            if received != expected:
                print(f"  MISMATCH: {path}  got={len(received)}  want={len(expected)}")
                errors += 1

        elapsed = time.perf_counter() - t0
        total_bytes = num_files * size_kb * 1024
        throughput = total_bytes / elapsed / 1024 / 1024

        stop_event.set()
        await server_task

        print(f"  Files served:  {num_files}")
        print(f"  Total data:    {total_bytes / 1024:.0f} KiB")
        print(f"  Elapsed:       {elapsed*1000:.0f}ms")
        print(f"  Throughput:    {throughput:.1f} MiB/s")
        print(f"  Errors:        {errors}")
        print()
        if errors == 0:
            print("All responses verified OK.")
        else:
            print(f"{errors} responses had content mismatches.")
            sys.exit(1)


async def serve_forever() -> None:
    """Run the server until Ctrl-C."""
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(__import__("signal").SIGINT, stop_event.set)
    print(f"Listening on {HOST}:{PORT}. Send a file path followed by newline.")
    print("Press Ctrl-C to stop.")
    await run_server(stop_event)


def main() -> None:
    parser = argparse.ArgumentParser(description="UringAsync file server example")
    parser.add_argument("--serve", action="store_true",
                        help="Run server in foreground (default: run self-test)")
    parser.add_argument("--files", type=int, default=10,
                        help="Number of test files for self-test (default: 10)")
    parser.add_argument("--size-kb", type=int, default=32,
                        help="Size of each test file in KiB (default: 32)")
    args = parser.parse_args()

    if args.serve:
        asyncio.run(serve_forever())
    else:
        asyncio.run(self_test(args.files, args.size_kb))


if __name__ == "__main__":
    main()
