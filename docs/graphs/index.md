# Example throughput charts

Bar charts for [`examples/README.md`](https://github.com/kangtegong/pyuring/blob/main/examples/README.md): **MiB/s**, **before** vs **pyuring**.

Workloads are **many small/medium files** (thread pool or `asyncio.gather`+executor vs batched io_uring), where batching usually favors pyuring. Regenerate with:

`pip install numpy`

`PYTHONPATH=. python3 scripts/gen_example_graphs.py`

## PyTorch-style (many shards)

![pytorch](example_pytorch_shards.svg)

## asyncio (many files)

![asyncio](example_asyncio_many_files.svg)

## FastAPI (many on-disk reads per batch)

![fastapi](example_fastapi_many_reads.svg)

## NumPy shards (`numpy_bins`)

![numpy_bins](example_numpy_bins.svg)

## Cached blob split into parts (`cached_reads`)

![cached_reads](example_cached_reads.svg)

## SQLite-export-style shard files (`sqlite_blobs`)

![sqlite_blobs](example_sqlite_blobs.svg)
