#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <liburing.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

static double now_sec(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static int ensure_file_allocated(const char *path, size_t size_bytes) {
  int fd = open(path, O_CREAT | O_RDWR, 0644);
  if (fd < 0) {
    return -errno;
  }
#ifdef __linux__
  int ret = posix_fallocate(fd, 0, (off_t)size_bytes);
  if (ret != 0) {
    // posix_fallocate returns error code, not -errno.
    close(fd);
    return -ret;
  }
#else
  if (ftruncate(fd, (off_t)size_bytes) != 0) {
    int e = errno;
    close(fd);
    return -e;
  }
#endif
  close(fd);
  return 0;
}

static void gen_offsets(uint64_t *out, unsigned n, uint64_t file_size, unsigned block_size,
                        uint64_t *state) {
  // LCG, deterministic
  uint64_t max_blocks = (file_size / block_size);
  if (max_blocks == 0) {
    for (unsigned i = 0; i < n; i++)
      out[i] = 0;
    return;
  }
  for (unsigned i = 0; i < n; i++) {
    *state = (*state * 6364136223846793005ULL) + 1ULL;
    uint64_t b = (*state) % max_blocks;
    out[i] = b * (uint64_t)block_size;
  }
}

// Return elapsed seconds, or negative errno as double (e.g. -5.0 for EIO)
double bench_pread_direct(const char *path, unsigned file_mb, unsigned block_size, unsigned reads_per_iter,
                          unsigned iters, unsigned seed) {
  size_t file_size = (size_t)file_mb * 1024u * 1024u;
  int ret = ensure_file_allocated(path, file_size);
  if (ret < 0) {
    return (double)ret;
  }

  int fd = open(path, O_RDONLY | O_DIRECT);
  if (fd < 0) {
    return (double)-errno;
  }

  void *buf = NULL;
  if (posix_memalign(&buf, 4096, (size_t)block_size) != 0) {
    close(fd);
    return (double)-ENOMEM;
  }

  uint64_t *offs = (uint64_t *)malloc((size_t)reads_per_iter * sizeof(uint64_t));
  if (!offs) {
    free(buf);
    close(fd);
    return (double)-ENOMEM;
  }

  uint64_t st = ((uint64_t)seed << 32) ^ 0x9e3779b97f4a7c15ULL;

  // Warmup
  gen_offsets(offs, reads_per_iter, (uint64_t)file_size, block_size, &st);
  ssize_t wn = pread(fd, buf, block_size, (off_t)offs[0]);
  if (wn < 0) {
    double e = (double)-errno;
    free(offs);
    free(buf);
    close(fd);
    return e;
  }

  double t0 = now_sec();
  for (unsigned it = 0; it < iters; it++) {
    gen_offsets(offs, reads_per_iter, (uint64_t)file_size, block_size, &st);
    for (unsigned i = 0; i < reads_per_iter; i++) {
      ssize_t n = pread(fd, buf, block_size, (off_t)offs[i]);
      if (n < 0) {
        double e = (double)-errno;
        free(offs);
        free(buf);
        close(fd);
        return e;
      }
      if ((unsigned)n != block_size) {
        // treat short read as error for benchmarking simplicity
        free(offs);
        free(buf);
        close(fd);
        return (double)-EIO;
      }
    }
  }
  double t1 = now_sec();

  free(offs);
  free(buf);
  close(fd);
  return t1 - t0;
}

// io_uring direct random reads with queue depth = reads_per_iter
double bench_uring_direct(const char *path, unsigned file_mb, unsigned block_size, unsigned reads_per_iter,
                          unsigned iters, unsigned seed, unsigned setup_flags) {
  size_t file_size = (size_t)file_mb * 1024u * 1024u;
  int ret = ensure_file_allocated(path, file_size);
  if (ret < 0) {
    return (double)ret;
  }

  int fd = open(path, O_RDONLY | O_DIRECT);
  if (fd < 0) {
    return (double)-errno;
  }

  // One big aligned buffer, split into blocks.
  void *buf = NULL;
  size_t buf_size = (size_t)block_size * (size_t)reads_per_iter;
  if (posix_memalign(&buf, 4096, buf_size) != 0) {
    close(fd);
    return (double)-ENOMEM;
  }

  uint64_t *offs = (uint64_t *)malloc((size_t)reads_per_iter * sizeof(uint64_t));
  if (!offs) {
    free(buf);
    close(fd);
    return (double)-ENOMEM;
  }

  struct io_uring_params p;
  memset(&p, 0, sizeof(p));
  p.flags = setup_flags;
  struct io_uring ring;
  int qret = io_uring_queue_init_params(reads_per_iter, &ring, &p);
  if (qret < 0) {
    // negative errno
    free(offs);
    free(buf);
    close(fd);
    return (double)qret;
  }

  uint64_t st = ((uint64_t)seed << 32) ^ 0xd1b54a32d192ed03ULL;

  // Warmup: one request
  gen_offsets(offs, reads_per_iter, (uint64_t)file_size, block_size, &st);
  struct io_uring_sqe *sqe0 = io_uring_get_sqe(&ring);
  if (!sqe0) {
    io_uring_queue_exit(&ring);
    free(offs);
    free(buf);
    close(fd);
    return (double)-EAGAIN;
  }
  io_uring_prep_read(sqe0, fd, buf, block_size, (off_t)offs[0]);
  sqe0->user_data = 1;
  qret = io_uring_submit_and_wait(&ring, 1);
  if (qret < 0) {
    io_uring_queue_exit(&ring);
    free(offs);
    free(buf);
    close(fd);
    return (double)qret;
  }
  struct io_uring_cqe *cqe0 = NULL;
  qret = io_uring_wait_cqe(&ring, &cqe0);
  if (qret < 0) {
    io_uring_queue_exit(&ring);
    free(offs);
    free(buf);
    close(fd);
    return (double)qret;
  }
  if (cqe0->res < 0) {
    double e = (double)cqe0->res;
    io_uring_cqe_seen(&ring, cqe0);
    io_uring_queue_exit(&ring);
    free(offs);
    free(buf);
    close(fd);
    return e;
  }
  io_uring_cqe_seen(&ring, cqe0);

  struct io_uring_cqe *cqes[256];

  double t0 = now_sec();
  for (unsigned it = 0; it < iters; it++) {
    gen_offsets(offs, reads_per_iter, (uint64_t)file_size, block_size, &st);

    for (unsigned i = 0; i < reads_per_iter; i++) {
      struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
      if (!sqe) {
        io_uring_queue_exit(&ring);
        free(offs);
        free(buf);
        close(fd);
        return (double)-EAGAIN;
      }
      void *dst = (void *)((char *)buf + ((size_t)i * (size_t)block_size));
      io_uring_prep_read(sqe, fd, dst, block_size, (off_t)offs[i]);
      sqe->user_data = (uint64_t)(i + 1);
    }

    qret = io_uring_submit_and_wait(&ring, reads_per_iter);
    if (qret < 0) {
      io_uring_queue_exit(&ring);
      free(offs);
      free(buf);
      close(fd);
      return (double)qret;
    }

    unsigned remaining = reads_per_iter;
    while (remaining) {
      unsigned want = remaining;
      if (want > (unsigned)(sizeof(cqes) / sizeof(cqes[0]))) {
        want = (unsigned)(sizeof(cqes) / sizeof(cqes[0]));
      }
      unsigned got = io_uring_peek_batch_cqe(&ring, cqes, want);
      if (!got) {
        struct io_uring_cqe *cqe = NULL;
        qret = io_uring_wait_cqe(&ring, &cqe);
        if (qret < 0) {
          io_uring_queue_exit(&ring);
          free(offs);
          free(buf);
          close(fd);
          return (double)qret;
        }
        if (cqe->res < 0) {
          double e = (double)cqe->res;
          io_uring_cqe_seen(&ring, cqe);
          io_uring_queue_exit(&ring);
          free(offs);
          free(buf);
          close(fd);
          return e;
        }
        io_uring_cqe_seen(&ring, cqe);
        remaining--;
        continue;
      }

      for (unsigned i = 0; i < got; i++) {
        if (cqes[i]->res < 0) {
          double e = (double)cqes[i]->res;
          io_uring_cq_advance(&ring, i + 1);
          io_uring_queue_exit(&ring);
          free(offs);
          free(buf);
          close(fd);
          return e;
        }
      }
      io_uring_cq_advance(&ring, got);
      remaining -= got;
    }
  }
  double t1 = now_sec();

  io_uring_queue_exit(&ring);
  free(offs);
  free(buf);
  close(fd);
  return t1 - t0;
}


