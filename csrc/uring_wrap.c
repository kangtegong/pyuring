#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <liburing.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#include <linux/falloc.h>
#include <linux/stat.h>
#include <netinet/in.h>
#include <sys/stat.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <unistd.h>

#include <linux/time_types.h>
#include <sys/epoll.h>
/* struct open_how comes from liburing compat / linux headers */

typedef struct uring_ctx {
  struct io_uring ring;
  unsigned entries;
} uring_ctx;

uring_ctx *uring_create_ex(unsigned entries, unsigned flags, int sq_thread_cpu, unsigned sq_thread_idle);

// Returns NULL on error (errno set).
uring_ctx *uring_create(unsigned entries) { return uring_create_ex(entries, 0, -1, 0); }

// Extended queue init: flags are IORING_SETUP_*; sq_thread_cpu < 0 leaves sq_thread_cpu unset.
uring_ctx *uring_create_ex(unsigned entries, unsigned flags, int sq_thread_cpu, unsigned sq_thread_idle) {
  uring_ctx *ctx = (uring_ctx *)calloc(1, sizeof(*ctx));
  if (!ctx) {
    return NULL;
  }
  ctx->entries = entries;

  struct io_uring_params p;
  memset(&p, 0, sizeof(p));
  p.flags = flags;
  if (sq_thread_cpu >= 0) {
    p.sq_thread_cpu = (unsigned int)sq_thread_cpu;
  }
  if (sq_thread_idle > 0 || (flags & IORING_SETUP_SQPOLL)) {
    p.sq_thread_idle = sq_thread_idle;
  }

  int ret = io_uring_queue_init_params((unsigned)entries, &ctx->ring, &p);
  if (ret < 0) {
    errno = -ret;
    free(ctx);
    return NULL;
  }
  return ctx;
}

void uring_destroy(uring_ctx *ctx) {
  if (!ctx) {
    return;
  }
  io_uring_queue_exit(&ctx->ring);
  free(ctx);
}

// io_uring CQ fd — poll(2) / epoll / asyncio loop.add_reader
int uring_ring_fd(const uring_ctx *ctx) {
  if (!ctx) {
    return -EINVAL;
  }
  return ctx->ring.ring_fd;
}

int uring_register_files(uring_ctx *ctx, const int *fds, unsigned nr) {
  if (!ctx || (!fds && nr > 0)) {
    return -EINVAL;
  }
  return io_uring_register_files(&ctx->ring, fds, nr);
}

int uring_unregister_files(uring_ctx *ctx) {
  if (!ctx) {
    return -EINVAL;
  }
  return io_uring_unregister_files(&ctx->ring);
}

int uring_register_buffers(uring_ctx *ctx, const struct iovec *iovecs, unsigned nr) {
  if (!ctx || (!iovecs && nr > 0)) {
    return -EINVAL;
  }
  return io_uring_register_buffers(&ctx->ring, iovecs, nr);
}

int uring_unregister_buffers(uring_ctx *ctx) {
  if (!ctx) {
    return -EINVAL;
  }
  return io_uring_unregister_buffers(&ctx->ring);
}

// Fixed file index + fixed buffer index (see io_uring_prep_read_fixed + IOSQE_FIXED_FILE).
int uring_read_fixed_sync(uring_ctx *ctx, unsigned file_index, void *buf, unsigned len, long long offset,
                          unsigned buf_index) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_read_fixed(sqe, (int)file_index, buf, len, (off_t)offset, (int)buf_index);
  sqe->flags |= IOSQE_FIXED_FILE;
  sqe->user_data = 3;

  int ret = io_uring_submit(&ctx->ring);
  if (ret < 0) {
    return ret;
  }

  struct io_uring_cqe *cqe = NULL;
  ret = io_uring_wait_cqe(&ctx->ring, &cqe);
  if (ret < 0) {
    return ret;
  }
  int res = cqe->res;
  io_uring_cqe_seen(&ctx->ring, cqe);
  return res;
}

int uring_write_fixed_sync(uring_ctx *ctx, unsigned file_index, const void *buf, unsigned len, long long offset,
                           unsigned buf_index) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_write_fixed(sqe, (int)file_index, buf, len, (off_t)offset, (int)buf_index);
  sqe->flags |= IOSQE_FIXED_FILE;
  sqe->user_data = 4;

  int ret = io_uring_submit(&ctx->ring);
  if (ret < 0) {
    return ret;
  }

  struct io_uring_cqe *cqe = NULL;
  ret = io_uring_wait_cqe(&ctx->ring, &cqe);
  if (ret < 0) {
    return ret;
  }
  int res = cqe->res;
  io_uring_cqe_seen(&ctx->ring, cqe);
  return res;
}

// Returns 1 if supported, 0 if not, negative errno on failure.
int uring_probe_opcode_supported(uring_ctx *ctx, int opcode) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_probe *probe = io_uring_get_probe_ring(&ctx->ring);
  if (!probe) {
    int e = errno;
    return e ? -e : -ENOMEM;
  }
  int ok = io_uring_opcode_supported(probe, opcode);
  io_uring_free_probe(probe);
  return ok ? 1 : 0;
}

// Writes (last_op+1) bytes: 1 if opcode index supported else 0. Returns count written (last_op+1) or negative errno.
int uring_probe_supported_mask(uring_ctx *ctx, unsigned char *out, unsigned out_cap) {
  if (!ctx || !out) {
    return -EINVAL;
  }
  struct io_uring_probe *probe = io_uring_get_probe_ring(&ctx->ring);
  if (!probe) {
    int e = errno;
    return e ? -e : -ENOMEM;
  }
  unsigned n = (unsigned)probe->last_op + 1u;
  if (out_cap < n) {
    io_uring_free_probe(probe);
    return -EINVAL;
  }
  for (unsigned i = 0; i < n; i++) {
    out[i] = io_uring_opcode_supported(probe, (int)i) ? 1 : 0;
  }
  io_uring_free_probe(probe);
  return (int)n;
}

int uring_probe_last_op(uring_ctx *ctx) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_probe *probe = io_uring_get_probe_ring(&ctx->ring);
  if (!probe) {
    int e = errno;
    return e ? -e : -ENOMEM;
  }
  int lo = (int)probe->last_op;
  io_uring_free_probe(probe);
  return lo;
}

// Synchronous helper: prepare->submit->wait for completion.
// Returns >=0 result (bytes), or negative errno (e.g. -EIO).
int uring_read_sync(uring_ctx *ctx, int fd, void *buf, unsigned len, long long offset) {
  if (!ctx) {
    return -EINVAL;
  }

  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }

  io_uring_prep_read(sqe, fd, buf, len, (off_t)offset);
  sqe->user_data = 1;

  int ret = io_uring_submit(&ctx->ring);
  if (ret < 0) {
    return ret; // negative errno
  }

  struct io_uring_cqe *cqe = NULL;
  ret = io_uring_wait_cqe(&ctx->ring, &cqe);
  if (ret < 0) {
    return ret; // negative errno
  }

  int res = cqe->res;
  io_uring_cqe_seen(&ctx->ring, cqe);
  return res;
}

int uring_write_sync(uring_ctx *ctx, int fd, const void *buf, unsigned len, long long offset) {
  if (!ctx) {
    return -EINVAL;
  }

  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }

  io_uring_prep_write(sqe, fd, buf, len, (off_t)offset);
  sqe->user_data = 2;

  int ret = io_uring_submit(&ctx->ring);
  if (ret < 0) {
    return ret; // negative errno
  }

  struct io_uring_cqe *cqe = NULL;
  ret = io_uring_wait_cqe(&ctx->ring, &cqe);
  if (ret < 0) {
    return ret; // negative errno
  }

  int res = cqe->res;
  io_uring_cqe_seen(&ctx->ring, cqe);
  return res;
}

// ============================================================================
// Asynchronous API with dynamic buffer size support
// ============================================================================

typedef struct uring_buffer_pool {
  void **buffers;
  unsigned *buffer_sizes;
  unsigned *buffer_capacities;
  unsigned count;
  unsigned max_capacity;
} uring_buffer_pool;

// Create a buffer pool for dynamic buffer management
// Returns NULL on error (errno set)
uring_buffer_pool *uring_buffer_pool_create(unsigned initial_count, unsigned initial_size) {
  uring_buffer_pool *pool = (uring_buffer_pool *)calloc(1, sizeof(*pool));
  if (!pool) {
    return NULL;
  }
  
  pool->count = initial_count;
  pool->max_capacity = initial_size;
  pool->buffers = (void **)calloc(initial_count, sizeof(void *));
  pool->buffer_sizes = (unsigned *)calloc(initial_count, sizeof(unsigned));
  pool->buffer_capacities = (unsigned *)calloc(initial_count, sizeof(unsigned));
  
  if (!pool->buffers || !pool->buffer_sizes || !pool->buffer_capacities) {
    free(pool->buffers);
    free(pool->buffer_sizes);
    free(pool->buffer_capacities);
    free(pool);
    return NULL;
  }
  
  // Allocate aligned buffers
  for (unsigned i = 0; i < initial_count; i++) {
    void *p = NULL;
    if (posix_memalign(&p, 4096, initial_size) != 0) {
      // Cleanup on failure
      for (unsigned j = 0; j < i; j++) {
        free(pool->buffers[j]);
      }
      free(pool->buffers);
      free(pool->buffer_sizes);
      free(pool->buffer_capacities);
      free(pool);
      return NULL;
    }
    pool->buffers[i] = p;
    pool->buffer_sizes[i] = 0;
    pool->buffer_capacities[i] = initial_size;
  }
  
  return pool;
}

// Resize a buffer in the pool
// Returns 0 on success, negative errno on error
int uring_buffer_pool_resize(uring_buffer_pool *pool, unsigned index, unsigned new_size) {
  if (!pool || index >= pool->count) {
    return -EINVAL;
  }
  
  if (new_size <= pool->buffer_capacities[index]) {
    // Can use existing buffer
    pool->buffer_sizes[index] = new_size;
    return 0;
  }
  
  // Need to reallocate
  void *new_buf = NULL;
  if (posix_memalign(&new_buf, 4096, new_size) != 0) {
    return -ENOMEM;
  }
  
  // Copy old data if any
  if (pool->buffers[index] && pool->buffer_sizes[index] > 0) {
    unsigned copy_size = pool->buffer_sizes[index];
    if (copy_size > new_size) {
      copy_size = new_size;
    }
    memcpy(new_buf, pool->buffers[index], copy_size);
  }
  
  free(pool->buffers[index]);
  pool->buffers[index] = new_buf;
  pool->buffer_sizes[index] = new_size;
  pool->buffer_capacities[index] = new_size;
  
  if (new_size > pool->max_capacity) {
    pool->max_capacity = new_size;
  }
  
  return 0;
}

// Get buffer pointer and size
void *uring_buffer_pool_get(uring_buffer_pool *pool, unsigned index, unsigned *size) {
  if (!pool || index >= pool->count) {
    if (size) *size = 0;
    return NULL;
  }
  if (size) *size = pool->buffer_sizes[index];
  return pool->buffers[index];
}

// Set buffer size (without reallocation, must be <= capacity)
int uring_buffer_pool_set_size(uring_buffer_pool *pool, unsigned index, unsigned size) {
  if (!pool || index >= pool->count || size > pool->buffer_capacities[index]) {
    return -EINVAL;
  }
  pool->buffer_sizes[index] = size;
  return 0;
}

void uring_buffer_pool_destroy(uring_buffer_pool *pool) {
  if (!pool) {
    return;
  }
  if (pool->buffers) {
    for (unsigned i = 0; i < pool->count; i++) {
      if (pool->buffers[i]) {
        free(pool->buffers[i]);
      }
    }
    free(pool->buffers);
  }
  free(pool->buffer_sizes);
  free(pool->buffer_capacities);
  free(pool);
}

// Submit an asynchronous read operation
// Returns user_data tag on success (>=0), negative errno on error
// The user_data is used to identify the completion later
long long uring_read_async(uring_ctx *ctx, int fd, void *buf, unsigned len, long long offset, uint64_t user_data) {
  if (!ctx) {
    return -EINVAL;
  }
  
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  
  io_uring_prep_read(sqe, fd, buf, len, (off_t)offset);
  sqe->user_data = user_data;
  
  int ret = io_uring_submit(&ctx->ring);
  if (ret < 0) {
    return ret; // negative errno
  }
  
  return (long long)user_data;
}

// Submit an asynchronous write operation
// Returns user_data tag on success (>=0), negative errno on error
long long uring_write_async(uring_ctx *ctx, int fd, const void *buf, unsigned len, long long offset, uint64_t user_data) {
  if (!ctx) {
    return -EINVAL;
  }
  
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  
  io_uring_prep_write(sqe, fd, buf, len, (off_t)offset);
  sqe->user_data = user_data;
  
  int ret = io_uring_submit(&ctx->ring);
  if (ret < 0) {
    return ret; // negative errno
  }
  
  return (long long)user_data;
}

// Wait for a completion (blocking)
// Returns 0 on success, negative errno on error
// On success, fills out: *user_data, *result (bytes read/written or negative errno)
int uring_wait_completion(uring_ctx *ctx, uint64_t *user_data, int *result) {
  if (!ctx || !user_data || !result) {
    return -EINVAL;
  }
  
  struct io_uring_cqe *cqe = NULL;
  int ret = io_uring_wait_cqe(&ctx->ring, &cqe);
  if (ret < 0) {
    return ret;
  }
  
  *user_data = cqe->user_data;
  *result = cqe->res;
  io_uring_cqe_seen(&ctx->ring, cqe);
  return 0;
}

// Peek at a completion without waiting (non-blocking)
// Returns 1 if completion found, 0 if none available, negative errno on error
int uring_peek_completion(uring_ctx *ctx, uint64_t *user_data, int *result) {
  if (!ctx || !user_data || !result) {
    return -EINVAL;
  }
  
  struct io_uring_cqe *cqe = NULL;
  int ret = io_uring_peek_cqe(&ctx->ring, &cqe);
  if (ret < 0) {
    if (ret == -EAGAIN) {
      return 0; // No completion available
    }
    return ret; // Error
  }
  
  if (!cqe) {
    return 0; // No completion available
  }
  
  *user_data = cqe->user_data;
  *result = cqe->res;
  io_uring_cqe_seen(&ctx->ring, cqe);
  return 1;
}

// Submit all queued operations
// Returns number of operations submitted, or negative errno
int uring_submit(uring_ctx *ctx) {
  if (!ctx) {
    return -EINVAL;
  }
  return io_uring_submit(&ctx->ring);
}

// Wait for at least 'wait_nr' completions, then submit any queued operations
// Returns number of operations submitted, or negative errno
int uring_submit_and_wait(uring_ctx *ctx, unsigned wait_nr) {
  if (!ctx) {
    return -EINVAL;
  }
  return io_uring_submit_and_wait(&ctx->ring, wait_nr);
}

// Batch pread: submit 'blocks' reads of 'block_size' bytes each into a single buffer.
// 'buf' must have at least block_size*blocks capacity.
// Returns total bytes read (sum of CQEs), or negative errno.
int uring_read_batch_sync(uring_ctx *ctx, int fd, void *buf, unsigned block_size, unsigned blocks,
                          long long offset) {
  if (!ctx || !buf || block_size == 0 || blocks == 0) {
    return -EINVAL;
  }
  if (blocks > ctx->entries) {
    return -EINVAL;
  }

  // Enqueue all SQEs first.
  for (unsigned i = 0; i < blocks; i++) {
    struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
    if (!sqe) {
      return -EAGAIN;
    }
    void *dst = (void *)((char *)buf + ((size_t)i * (size_t)block_size));
    io_uring_prep_read(sqe, fd, dst, block_size, (off_t)(offset + (long long)i * (long long)block_size));
    sqe->user_data = (uint64_t)(i + 1);
  }

  // Submit once and wait for N completions with (typically) a single syscall.
  int ret = io_uring_submit_and_wait(&ctx->ring, blocks);
  if (ret < 0) {
    return ret;
  }

  struct io_uring_cqe *cqes[256];
  unsigned remaining = blocks;
  int total = 0;

  while (remaining) {
    unsigned want = remaining;
    if (want > (unsigned)(sizeof(cqes) / sizeof(cqes[0]))) {
      want = (unsigned)(sizeof(cqes) / sizeof(cqes[0]));
    }
    unsigned got = io_uring_peek_batch_cqe(&ctx->ring, cqes, want);
    if (!got) {
      // Should be rare after submit_and_wait, but be safe.
      struct io_uring_cqe *cqe = NULL;
      ret = io_uring_wait_cqe(&ctx->ring, &cqe);
      if (ret < 0) {
        return ret;
      }
      int res = cqe->res;
      io_uring_cqe_seen(&ctx->ring, cqe);
      if (res < 0) {
        return res;
      }
      total += res;
      remaining--;
      continue;
    }

    for (unsigned i = 0; i < got; i++) {
      int res = cqes[i]->res;
      if (res < 0) {
        // Mark what we consumed so far as seen, then return error.
        io_uring_cq_advance(&ctx->ring, i + 1);
        return res;
      }
      total += res;
    }
    io_uring_cq_advance(&ctx->ring, got);
    remaining -= got;
  }

  return total;
}

// Batch pread with per-request offsets.
// 'offsets' must point to an array of 'blocks' offsets (bytes).
// 'buf' must have block_size*blocks capacity.
// Returns total bytes read (sum), or negative errno.
int uring_read_offsets_sync(uring_ctx *ctx, int fd, void *buf, unsigned block_size, const long long *offsets,
                            unsigned blocks) {
  if (!ctx || !buf || !offsets || block_size == 0 || blocks == 0) {
    return -EINVAL;
  }
  if (blocks > ctx->entries) {
    return -EINVAL;
  }

  for (unsigned i = 0; i < blocks; i++) {
    struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
    if (!sqe) {
      return -EAGAIN;
    }
    void *dst = (void *)((char *)buf + ((size_t)i * (size_t)block_size));
    io_uring_prep_read(sqe, fd, dst, block_size, (off_t)offsets[i]);
    sqe->user_data = (uint64_t)(i + 1);
  }

  int ret = io_uring_submit_and_wait(&ctx->ring, blocks);
  if (ret < 0) {
    return ret;
  }

  struct io_uring_cqe *cqes[256];
  unsigned remaining = blocks;
  int total = 0;

  while (remaining) {
    unsigned want = remaining;
    if (want > (unsigned)(sizeof(cqes) / sizeof(cqes[0]))) {
      want = (unsigned)(sizeof(cqes) / sizeof(cqes[0]));
    }
    unsigned got = io_uring_peek_batch_cqe(&ctx->ring, cqes, want);
    if (!got) {
      struct io_uring_cqe *cqe = NULL;
      ret = io_uring_wait_cqe(&ctx->ring, &cqe);
      if (ret < 0) {
        return ret;
      }
      int res = cqe->res;
      io_uring_cqe_seen(&ctx->ring, cqe);
      if (res < 0) {
        return res;
      }
      total += res;
      remaining--;
      continue;
    }

    for (unsigned i = 0; i < got; i++) {
      int res = cqes[i]->res;
      if (res < 0) {
        io_uring_cq_advance(&ctx->ring, i + 1);
        return res;
      }
      total += res;
    }
    io_uring_cq_advance(&ctx->ring, got);
    remaining -= got;
  }

  return total;
}

typedef struct copy_slot {
  char *buf;
  uint64_t off;
  uint32_t len;
  uint8_t active;
} copy_slot;

static inline uint64_t pack_ud(uint32_t op, uint32_t slot) {
  return ((uint64_t)op << 32) | (uint64_t)slot;
}
static inline uint32_t ud_op(uint64_t ud) { return (uint32_t)(ud >> 32); }
static inline uint32_t ud_slot(uint64_t ud) { return (uint32_t)(ud & 0xffffffffu); }

// Callback function type for dynamic buffer size adjustment.
// Parameters: current_offset, total_bytes, default_block_size, user_data
// Returns: desired buffer size for next write (must be <= max_buffer_size)
typedef unsigned (*buffer_size_callback_t)(uint64_t current_offset, uint64_t total_bytes, 
                                           unsigned default_block_size, void *user_data);

// Forward declaration
long long uring_write_newfile_dynamic(const char *dst_path, unsigned total_mb, unsigned block_size, unsigned qd,
                                     int do_fsync, int dsync_each_write,
                                     buffer_size_callback_t buffer_size_cb, void *user_data);
long long uring_copy_path_dynamic(const char *src_path, const char *dst_path, unsigned qd, unsigned block_size,
                                 buffer_size_callback_t buffer_size_cb, void *user_data, int do_fsync);

// Copy file using io_uring pipelined read->write.
// Returns bytes copied, or negative errno.
long long uring_copy_path(const char *src_path, const char *dst_path, unsigned qd, unsigned block_size) {
  return uring_copy_path_dynamic(src_path, dst_path, qd, block_size, NULL, NULL, 0);
}

// Copy file using io_uring pipelined read->write with dynamically adjustable buffer sizes.
// buffer_size_cb: callback to determine buffer size for each read/write (NULL = use block_size)
// user_data: passed to callback
// do_fsync: if non-zero, fsync destination file at the end
// Returns bytes copied, or negative errno.
long long uring_copy_path_dynamic(const char *src_path, const char *dst_path, unsigned qd, unsigned block_size,
                                 buffer_size_callback_t buffer_size_cb, void *user_data, int do_fsync) {
  if (!src_path || !dst_path || qd == 0 || block_size == 0) {
    return -EINVAL;
  }

  int sfd = open(src_path, O_RDONLY);
  if (sfd < 0) {
    return -errno;
  }
  int dfd = open(dst_path, O_CREAT | O_TRUNC | O_WRONLY, 0644);
  if (dfd < 0) {
    int e = errno;
    close(sfd);
    return -e;
  }

  struct stat st;
  if (fstat(sfd, &st) != 0) {
    int e = errno;
    close(dfd);
    close(sfd);
    return -e;
  }

  uint64_t file_size = (uint64_t)st.st_size;
  if (file_size == 0) {
    close(dfd);
    close(sfd);
    return 0;
  }

  // Determine maximum buffer size needed
  unsigned max_buffer_size = block_size;
  if (buffer_size_cb) {
    // Probe callback to find maximum buffer size it might return
    for (uint64_t test_off = 0; test_off < file_size; test_off += block_size) {
      unsigned test_size = buffer_size_cb(test_off, file_size, block_size, user_data);
      if (test_size > max_buffer_size) {
        max_buffer_size = test_size;
      }
      // Limit to reasonable maximum (e.g., 64MB)
      if (max_buffer_size > (64u * 1024u * 1024u)) {
        max_buffer_size = 64u * 1024u * 1024u;
        break;
      }
    }
  }

  struct io_uring ring;
  int ret = io_uring_queue_init(qd, &ring, 0);
  if (ret < 0) {
    close(dfd);
    close(sfd);
    return ret;
  }

  copy_slot *slots = (copy_slot *)calloc(qd, sizeof(copy_slot));
  if (!slots) {
    io_uring_queue_exit(&ring);
    close(dfd);
    close(sfd);
    return -ENOMEM;
  }

  // Allocate buffers with max_buffer_size
  for (unsigned i = 0; i < qd; i++) {
    void *p = NULL;
    if (posix_memalign(&p, 4096, max_buffer_size) != 0) {
      for (unsigned j = 0; j < i; j++) {
        free(slots[j].buf);
      }
      free(slots);
      io_uring_queue_exit(&ring);
      close(dfd);
      close(sfd);
      return -ENOMEM;
    }
    slots[i].buf = (char *)p;
  }

  uint64_t next_off = 0;
  unsigned inflight = 0;
  long long copied = 0;

  // Prime the queue with initial reads.
  for (unsigned i = 0; i < qd && next_off < file_size; i++) {
    // Determine buffer size: use callback if provided, otherwise use block_size
    uint32_t want = block_size;
    if (buffer_size_cb) {
      unsigned cb_size = buffer_size_cb(next_off, file_size, block_size, user_data);
      if (cb_size > 0 && cb_size <= max_buffer_size) {
        want = cb_size;
      }
    }
    
    uint64_t remain = file_size - next_off;
    if (remain < (uint64_t)want) {
      want = (uint32_t)remain;
    }
    slots[i].off = next_off;
    slots[i].len = want;
    slots[i].active = 1;

    struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
    if (!sqe) {
      ret = -EAGAIN;
      goto out;
    }
    io_uring_prep_read(sqe, sfd, slots[i].buf, want, (off_t)next_off);
    sqe->user_data = pack_ud(0, i); // 0=read
    inflight++;
    next_off += want;
  }

  ret = io_uring_submit(&ring);
  if (ret < 0) {
    goto out;
  }

  while (inflight) {
    struct io_uring_cqe *cqe = NULL;
    ret = io_uring_wait_cqe(&ring, &cqe);
    if (ret < 0) {
      goto out;
    }

    uint64_t ud = cqe->user_data;
    uint32_t op = ud_op(ud);
    uint32_t slot = ud_slot(ud);
    int res = cqe->res;
    io_uring_cqe_seen(&ring, cqe);
    inflight--;

    if (slot >= qd || !slots[slot].active) {
      ret = -EIO;
      goto out;
    }

    if (res < 0) {
      ret = res; // negative errno
      goto out;
    }

    if (op == 0) {
      // read completion: res is bytes read
      if (res == 0) {
        // EOF for this slot; stop using it.
        slots[slot].active = 0;
      } else {
        struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
        if (!sqe) {
          ret = -EAGAIN;
          goto out;
        }
        io_uring_prep_write(sqe, dfd, slots[slot].buf, (unsigned)res, (off_t)slots[slot].off);
        sqe->user_data = pack_ud(1, slot); // 1=write
        inflight++;
        ret = io_uring_submit(&ring);
        if (ret < 0) {
          goto out;
        }
      }
    } else {
      // write completion
      copied += res;

      // schedule next read for this slot if remaining
      if (next_off < file_size) {
        // Determine buffer size: use callback if provided, otherwise use block_size
        uint32_t want = block_size;
        if (buffer_size_cb) {
          unsigned cb_size = buffer_size_cb(next_off, file_size, block_size, user_data);
          if (cb_size > 0 && cb_size <= max_buffer_size) {
            want = cb_size;
          }
        }
        
        uint64_t remain = file_size - next_off;
        if (remain < (uint64_t)want) {
          want = (uint32_t)remain;
        }
        slots[slot].off = next_off;
        slots[slot].len = want;

        struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
        if (!sqe) {
          ret = -EAGAIN;
          goto out;
        }
        io_uring_prep_read(sqe, sfd, slots[slot].buf, want, (off_t)next_off);
        sqe->user_data = pack_ud(0, slot);
        inflight++;
        next_off += want;

        ret = io_uring_submit(&ring);
        if (ret < 0) {
          goto out;
        }
      } else {
        slots[slot].active = 0;
      }
    }
  }

  // Ensure dst size is correct even if short last write (shouldn't happen normally).
  if (ftruncate(dfd, (off_t)copied) != 0) {
    // Not fatal for copy semantics; keep best-effort.
  }

  if (do_fsync) {
    if (fsync(dfd) != 0) {
      ret = -errno;
      goto out;
    }
  }

out:
  for (unsigned i = 0; i < qd; i++) {
    free(slots[i].buf);
  }
  free(slots);
  io_uring_queue_exit(&ring);
  close(dfd);
  close(sfd);
  if (ret < 0) {
    return (long long)ret;
  }
  return copied;
}

// Write a brand-new file with many small sequential writes using io_uring pipeline.
// Returns bytes written, or negative errno.
long long uring_write_newfile(const char *dst_path, unsigned total_mb, unsigned block_size, unsigned qd,
                              int do_fsync, int dsync_each_write) {
  return uring_write_newfile_dynamic(dst_path, total_mb, block_size, qd, do_fsync, dsync_each_write, NULL, NULL);
}

// Write a brand-new file with dynamically adjustable buffer sizes.
// buffer_size_cb: callback to determine buffer size for each write (NULL = use block_size)
// user_data: passed to callback
// Returns bytes written, or negative errno.
long long uring_write_newfile_dynamic(const char *dst_path, unsigned total_mb, unsigned block_size, unsigned qd,
                                      int do_fsync, int dsync_each_write,
                                      buffer_size_callback_t buffer_size_cb, void *user_data) {
  if (!dst_path || total_mb == 0 || block_size == 0 || qd == 0) {
    return -EINVAL;
  }

  uint64_t total_bytes = (uint64_t)total_mb * 1024u * 1024u;
  if (total_bytes < block_size) {
    total_bytes = block_size;
  }

  // Determine maximum buffer size needed
  unsigned max_buffer_size = block_size;
  if (buffer_size_cb) {
    // Probe callback to find maximum buffer size it might return
    for (uint64_t test_off = 0; test_off < total_bytes; test_off += block_size) {
      unsigned test_size = buffer_size_cb(test_off, total_bytes, block_size, user_data);
      if (test_size > max_buffer_size) {
        max_buffer_size = test_size;
      }
      // Limit to reasonable maximum (e.g., 64MB)
      if (max_buffer_size > (64u * 1024u * 1024u)) {
        max_buffer_size = 64u * 1024u * 1024u;
        break;
      }
    }
  }

  int dfd = open(dst_path, O_CREAT | O_TRUNC | O_WRONLY, 0644);
  if (dfd < 0) {
    return -errno;
  }

  struct io_uring ring;
  int ret = io_uring_queue_init(qd, &ring, 0);
  if (ret < 0) {
    close(dfd);
    return ret;
  }

  // Buffer pool: allocate max_buffer_size for each slot
  copy_slot *slots = (copy_slot *)calloc(qd, sizeof(copy_slot));
  if (!slots) {
    io_uring_queue_exit(&ring);
    close(dfd);
    return -ENOMEM;
  }
  for (unsigned i = 0; i < qd; i++) {
    void *p = NULL;
    if (posix_memalign(&p, 4096, max_buffer_size) != 0) {
      for (unsigned j = 0; j < i; j++) {
        free(slots[j].buf);
      }
      free(slots);
      io_uring_queue_exit(&ring);
      close(dfd);
      return -ENOMEM;
    }
    slots[i].buf = (char *)p;
    slots[i].active = 1;
    // Fill deterministic pattern once (avoids per-write memset cost differences).
    // Fill up to max_buffer_size to ensure we have data for any size
    for (unsigned k = 0; k < max_buffer_size; k++) {
      slots[i].buf[k] = (char)('A' + (char)((i + k) % 26));
    }
  }

  uint64_t next_off = 0;
  unsigned inflight = 0;      // submitted but not completed
  unsigned pending = 0;       // SQEs queued but not yet submitted
  long long written = 0;

  struct io_uring_cqe *cqes[256];

  // Main loop: keep QD writes in-flight; submit in batches; reap CQEs in batches.
  while (next_off < total_bytes || inflight || pending) {
    // Queue as many SQEs as possible up to qd in-flight.
    while (next_off < total_bytes && (inflight + pending) < qd) {
      // Find a slot to reuse: we map slot id to the sqe user_data. For writes, we can reuse any slot id.
      // Use slot index equal to (next_off / block_size) % qd for stable reuse.
      uint32_t slot = (uint32_t)(((next_off / (uint64_t)block_size) % (uint64_t)qd));

      // Determine buffer size: use callback if provided, otherwise use block_size
      uint32_t want = block_size;
      if (buffer_size_cb) {
        unsigned cb_size = buffer_size_cb(next_off, total_bytes, block_size, user_data);
        if (cb_size > 0 && cb_size <= max_buffer_size) {
          want = cb_size;
        }
      }
      
      uint64_t remain = total_bytes - next_off;
      if (remain < (uint64_t)want) {
        want = (uint32_t)remain;
      }
      slots[slot].off = next_off;
      slots[slot].len = want;

      struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
      if (!sqe) {
        break; // SQ full; submit/reap then retry
      }
      io_uring_prep_write(sqe, dfd, slots[slot].buf, want, (off_t)next_off);
      if (dsync_each_write) {
        sqe->rw_flags |= RWF_DSYNC;
      }
      sqe->user_data = pack_ud(1, slot);
      pending++;
      next_off += want;
    }

    if (pending) {
      // submit all queued SQEs; then wait for at least 1 completion to avoid busy looping
      ret = io_uring_submit(&ring);
      if (ret < 0) {
        goto out;
      }
      inflight += pending;
      pending = 0;
    }

    if (!inflight) {
      continue;
    }

    // Wait for at least one completion, then reap as many as available in batch.
    ret = io_uring_submit_and_wait(&ring, 1);
    if (ret < 0) {
      goto out;
    }

    while (inflight) {
      unsigned got = io_uring_peek_batch_cqe(&ring, cqes, (unsigned)(sizeof(cqes) / sizeof(cqes[0])));
      if (!got) {
        break;
      }

      for (unsigned i = 0; i < got; i++) {
        uint64_t ud = cqes[i]->user_data;
        uint32_t op = ud_op(ud);
        uint32_t slot = ud_slot(ud);
        int res = cqes[i]->res;

        if (op != 1 || slot >= qd) {
          io_uring_cq_advance(&ring, i + 1);
          ret = -EIO;
          goto out;
        }
        if (res < 0) {
          io_uring_cq_advance(&ring, i + 1);
          ret = res;
          goto out;
        }
        written += res;
      }

      io_uring_cq_advance(&ring, got);
      inflight -= got;
    }
  }

  if (do_fsync) {
    if (fsync(dfd) != 0) {
      // if fsync fails, surface error
      ret = -errno;
      goto out;
    }
  }

out:
  for (unsigned i = 0; i < qd; i++) {
    free(slots[i].buf);
  }
  free(slots);
  io_uring_queue_exit(&ring);
  close(dfd);
  if (ret < 0) {
    return (long long)ret;
  }
  return written;
}

// Write N brand-new files in 'dir_path', each of size mb_per_file, using io_uring with queue depth qd.
// Pattern: many small sequential writes across files (round-robin), keeping QD in-flight.
// Returns total bytes written across all files, or negative errno.
long long uring_write_manyfiles(const char *dir_path, unsigned nfiles, unsigned mb_per_file, unsigned block_size,
                                unsigned qd, int do_fsync_end) {
  if (!dir_path || nfiles == 0 || mb_per_file == 0 || block_size == 0 || qd == 0) {
    return -EINVAL;
  }

  uint64_t per_file_bytes = (uint64_t)mb_per_file * 1024u * 1024u;
  uint64_t total_bytes = per_file_bytes * (uint64_t)nfiles;

  int *fds = (int *)calloc(nfiles, sizeof(int));
  if (!fds) {
    return -ENOMEM;
  }

  // Create/open all files
  for (unsigned i = 0; i < nfiles; i++) {
    char path[512];
    // name: dir/file_000000.dat
    int n = snprintf(path, sizeof(path), "%s/file_%06u.dat", dir_path, i);
    if (n <= 0 || (size_t)n >= sizeof(path)) {
      for (unsigned j = 0; j < i; j++)
        close(fds[j]);
      free(fds);
      return -ENAMETOOLONG;
    }
    int fd = open(path, O_CREAT | O_TRUNC | O_WRONLY, 0644);
    if (fd < 0) {
      int e = errno;
      for (unsigned j = 0; j < i; j++)
        close(fds[j]);
      free(fds);
      return -e;
    }
    fds[i] = fd;
  }

  struct io_uring ring;
  int ret = io_uring_queue_init(qd, &ring, 0);
  if (ret < 0) {
    for (unsigned i = 0; i < nfiles; i++)
      close(fds[i]);
    free(fds);
    return ret;
  }

  // Slot metadata: reuse copy_slot but interpret off as file offset, and store file index in len upper bits not safe.
  // Create dedicated arrays.
  copy_slot *slots = (copy_slot *)calloc(qd, sizeof(copy_slot));
  unsigned *slot_file = (unsigned *)calloc(qd, sizeof(unsigned));
  if (!slots || !slot_file) {
    free(slot_file);
    free(slots);
    io_uring_queue_exit(&ring);
    for (unsigned i = 0; i < nfiles; i++)
      close(fds[i]);
    free(fds);
    return -ENOMEM;
  }

  for (unsigned i = 0; i < qd; i++) {
    void *p = NULL;
    if (posix_memalign(&p, 4096, block_size) != 0) {
      for (unsigned j = 0; j < i; j++)
        free(slots[j].buf);
      free(slot_file);
      free(slots);
      io_uring_queue_exit(&ring);
      for (unsigned k = 0; k < nfiles; k++)
        close(fds[k]);
      free(fds);
      return -ENOMEM;
    }
    slots[i].buf = (char *)p;
    slots[i].active = 1;
    // deterministic content
    for (unsigned k = 0; k < block_size; k++) {
      slots[i].buf[k] = (char)('a' + (char)((i + k) % 26));
    }
  }

  uint64_t *file_off = (uint64_t *)calloc(nfiles, sizeof(uint64_t));
  if (!file_off) {
    for (unsigned i = 0; i < qd; i++)
      free(slots[i].buf);
    free(slot_file);
    free(slots);
    io_uring_queue_exit(&ring);
    for (unsigned k = 0; k < nfiles; k++)
      close(fds[k]);
    free(fds);
    return -ENOMEM;
  }
  uint8_t *file_done = (uint8_t *)calloc(nfiles, sizeof(uint8_t));
  if (!file_done) {
    free(file_off);
    for (unsigned i = 0; i < qd; i++)
      free(slots[i].buf);
    free(slot_file);
    free(slots);
    io_uring_queue_exit(&ring);
    for (unsigned k = 0; k < nfiles; k++)
      close(fds[k]);
    free(fds);
    return -ENOMEM;
  }

  unsigned *free_slots = (unsigned *)malloc((size_t)qd * sizeof(unsigned));
  if (!free_slots) {
    free(file_done);
    free(file_off);
    for (unsigned i = 0; i < qd; i++)
      free(slots[i].buf);
    free(slot_file);
    free(slots);
    io_uring_queue_exit(&ring);
    for (unsigned k = 0; k < nfiles; k++)
      close(fds[k]);
    free(fds);
    return -ENOMEM;
  }
  unsigned free_count = qd;
  for (unsigned i = 0; i < qd; i++) {
    free_slots[i] = i;
  }

  struct io_uring_cqe *cqes[256];
  unsigned inflight = 0; // submitted, not yet completed
  long long written = 0;
  unsigned done_files = 0;
  unsigned rr = 0;

  // Main loop
  while ((unsigned long long)written < (unsigned long long)total_bytes || inflight) {
    unsigned queued = 0;

    // enqueue as much as possible while we have free slots and unfinished files
    while (free_count && done_files < nfiles) {
      unsigned f = 0;
      uint64_t off = 0;
      uint32_t len = 0;

      int found = 0;
      for (unsigned tries = 0; tries < nfiles; tries++) {
        unsigned idx = rr++ % nfiles;
        if (file_done[idx]) {
          continue;
        }
        off = file_off[idx];
        if (off >= per_file_bytes) {
          file_done[idx] = 1;
          done_files++;
          continue;
        }
        uint32_t want = block_size;
        uint64_t remain = per_file_bytes - off;
        if (remain < (uint64_t)want) {
          want = (uint32_t)remain;
        }
        f = idx;
        len = want;
        file_off[idx] = off + want;
        if (file_off[idx] >= per_file_bytes) {
          file_done[idx] = 1;
          done_files++;
        }
        found = 1;
        break;
      }
      if (!found) {
        break;
      }

      unsigned slot = free_slots[--free_count];
      slot_file[slot] = f;
      slots[slot].off = off;
      slots[slot].len = len;

      struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
      if (!sqe) {
        // SQ is full; put slot back and submit/reap
        free_slots[free_count++] = slot;
        break;
      }
      io_uring_prep_write(sqe, fds[f], slots[slot].buf, len, (off_t)off);
      sqe->user_data = pack_ud(1, (uint32_t)slot);
      inflight++;
      queued++;
    }

    if (queued) {
      ret = io_uring_submit(&ring);
      if (ret < 0) {
        goto out;
      }
    }

    if (!inflight) {
      break;
    }

    ret = io_uring_submit_and_wait(&ring, 1);
    if (ret < 0) {
      goto out;
    }

    unsigned got = io_uring_peek_batch_cqe(&ring, cqes, (unsigned)(sizeof(cqes) / sizeof(cqes[0])));
    if (!got) {
      // fallback: wait one
      struct io_uring_cqe *cqe = NULL;
      ret = io_uring_wait_cqe(&ring, &cqe);
      if (ret < 0) {
        goto out;
      }
      cqes[0] = cqe;
      got = 1;
    }

    for (unsigned i = 0; i < got; i++) {
      uint64_t ud = cqes[i]->user_data;
      uint32_t op = ud_op(ud);
      uint32_t slot = ud_slot(ud);
      int res = cqes[i]->res;
      if (op != 1 || slot >= qd) {
        io_uring_cq_advance(&ring, i + 1);
        ret = -EIO;
        goto out;
      }
      if (res < 0) {
        io_uring_cq_advance(&ring, i + 1);
        ret = res;
        goto out;
      }
      written += res;
      inflight--;
      free_slots[free_count++] = slot;
    }
    io_uring_cq_advance(&ring, got);
  }

  if (do_fsync_end) {
    for (unsigned i = 0; i < nfiles; i++) {
      if (fsync(fds[i]) != 0) {
        ret = -errno;
        goto out;
      }
    }
  }

out:
  free(free_slots);
  free(file_done);
  free(file_off);
  for (unsigned i = 0; i < qd; i++)
    free(slots[i].buf);
  free(slot_file);
  free(slots);
  io_uring_queue_exit(&ring);
  for (unsigned i = 0; i < nfiles; i++)
    close(fds[i]);
  free(fds);
  if (ret < 0) {
    return (long long)ret;
  }
  return written;
}

// ============================================================================
// Extended synchronous op wrappers (readv, vfs, sockets, splice, timeout, link)
// ============================================================================

static int uring_submit_wait_one(uring_ctx *ctx) {
  if (!ctx) {
    return -EINVAL;
  }
  int ret = io_uring_submit(&ctx->ring);
  if (ret < 0) {
    return ret;
  }
  struct io_uring_cqe *cqe = NULL;
  ret = io_uring_wait_cqe(&ctx->ring, &cqe);
  if (ret < 0) {
    return ret;
  }
  int res = cqe->res;
  io_uring_cqe_seen(&ctx->ring, cqe);
  return res;
}

int uring_nop_sync(uring_ctx *ctx) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_nop(sqe);
  sqe->user_data = 199;
  return uring_submit_wait_one(ctx);
}

int uring_readv_sync(uring_ctx *ctx, int fd, struct iovec *iov, unsigned iovcnt, long long offset) {
  if (!ctx || !iov || iovcnt == 0) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_readv(sqe, fd, iov, iovcnt, (off_t)offset);
  sqe->user_data = 200;
  return uring_submit_wait_one(ctx);
}

int uring_writev_sync(uring_ctx *ctx, int fd, struct iovec *iov, unsigned iovcnt, long long offset) {
  if (!ctx || !iov || iovcnt == 0) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_writev(sqe, fd, iov, iovcnt, (off_t)offset);
  sqe->user_data = 201;
  return uring_submit_wait_one(ctx);
}

int uring_openat_sync(uring_ctx *ctx, int dfd, const char *path, int flags, unsigned int mode) {
  if (!ctx || !path) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_openat(sqe, dfd, path, flags, (mode_t)mode);
  sqe->user_data = 202;
  return uring_submit_wait_one(ctx);
}

int uring_close_sync(uring_ctx *ctx, int fd) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_close(sqe, fd);
  sqe->user_data = 203;
  return uring_submit_wait_one(ctx);
}

int uring_fsync_sync(uring_ctx *ctx, int fd, unsigned int fsync_flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_fsync(sqe, fd, fsync_flags);
  sqe->user_data = 204;
  return uring_submit_wait_one(ctx);
}

int uring_fallocate_sync(uring_ctx *ctx, int fd, int mode, uint64_t offset, uint64_t len) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_fallocate(sqe, fd, mode, offset, len);
  sqe->user_data = 205;
  return uring_submit_wait_one(ctx);
}

int uring_statx_sync(uring_ctx *ctx, int dfd, const char *path, int flags, unsigned int mask,
                     struct statx *statxbuf) {
  if (!ctx || !path || !statxbuf) {
    return -EINVAL;
  }
  memset(statxbuf, 0, sizeof(*statxbuf));
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_statx(sqe, dfd, path, flags, mask, statxbuf);
  sqe->user_data = 206;
  return uring_submit_wait_one(ctx);
}

int uring_renameat_sync(uring_ctx *ctx, int olddfd, const char *oldpath, int newdfd, const char *newpath,
                       unsigned int flags) {
  if (!ctx || !oldpath || !newpath) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_renameat(sqe, olddfd, oldpath, newdfd, newpath, flags);
  sqe->user_data = 207;
  return uring_submit_wait_one(ctx);
}

int uring_unlinkat_sync(uring_ctx *ctx, int dfd, const char *path, int flags) {
  if (!ctx || !path) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_unlinkat(sqe, dfd, path, flags);
  sqe->user_data = 208;
  return uring_submit_wait_one(ctx);
}

int uring_mkdirat_sync(uring_ctx *ctx, int dfd, const char *path, unsigned int mode) {
  if (!ctx || !path) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_mkdirat(sqe, dfd, path, (mode_t)mode);
  sqe->user_data = 209;
  return uring_submit_wait_one(ctx);
}

int uring_send_sync(uring_ctx *ctx, int sockfd, const void *buf, size_t len, unsigned int flags) {
  if (!ctx || (!buf && len > 0)) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_send(sqe, sockfd, buf, len, (int)flags);
  sqe->user_data = 210;
  return uring_submit_wait_one(ctx);
}

int uring_recv_sync(uring_ctx *ctx, int sockfd, void *buf, size_t len, unsigned int flags) {
  if (!ctx || (!buf && len > 0)) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_recv(sqe, sockfd, buf, len, (int)flags);
  sqe->user_data = 211;
  return uring_submit_wait_one(ctx);
}

int uring_accept_sync(uring_ctx *ctx, int fd, struct sockaddr *addr, socklen_t *addrlen, int flags) {
  if (!ctx || !addrlen) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_accept(sqe, fd, addr, addrlen, flags);
  sqe->user_data = 212;
  return uring_submit_wait_one(ctx);
}

int uring_connect_sync(uring_ctx *ctx, int fd, const struct sockaddr *addr, socklen_t addrlen) {
  if (!ctx || !addr) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_connect(sqe, fd, addr, addrlen);
  sqe->user_data = 213;
  return uring_submit_wait_one(ctx);
}

int uring_shutdown_sync(uring_ctx *ctx, int fd, int how) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_shutdown(sqe, fd, how);
  sqe->user_data = 214;
  return uring_submit_wait_one(ctx);
}

int uring_splice_sync(uring_ctx *ctx, int fd_in, int64_t off_in, int fd_out, int64_t off_out,
                      unsigned int nbytes, unsigned int splice_flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_splice(sqe, fd_in, off_in, fd_out, off_out, nbytes, splice_flags);
  sqe->user_data = 215;
  return uring_submit_wait_one(ctx);
}

int uring_tee_sync(uring_ctx *ctx, int fd_in, int fd_out, unsigned int nbytes, unsigned int splice_flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_tee(sqe, fd_in, fd_out, nbytes, splice_flags);
  sqe->user_data = 228;
  return uring_submit_wait_one(ctx);
}

int uring_poll_add_sync(uring_ctx *ctx, int fd, unsigned int poll_mask, uint64_t user_data) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_poll_add(sqe, fd, poll_mask);
  sqe->user_data = user_data;
  return uring_submit_wait_one(ctx);
}

int uring_poll_remove_sync(uring_ctx *ctx, uint64_t target_user_data) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_poll_remove(sqe, target_user_data);
  sqe->user_data = 229;
  return uring_submit_wait_one(ctx);
}

int uring_symlinkat_sync(uring_ctx *ctx, const char *target, int newdirfd, const char *linkpath) {
  if (!ctx || !target || !linkpath) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_symlinkat(sqe, target, newdirfd, linkpath);
  sqe->user_data = 230;
  return uring_submit_wait_one(ctx);
}

int uring_linkat_sync(uring_ctx *ctx, int olddfd, const char *oldpath, int newdfd, const char *newpath, int flags) {
  if (!ctx || !oldpath || !newpath) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_linkat(sqe, olddfd, oldpath, newdfd, newpath, flags);
  sqe->user_data = 231;
  return uring_submit_wait_one(ctx);
}

int uring_sync_file_range_sync(uring_ctx *ctx, int fd, unsigned int len, uint64_t offset, int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_sync_file_range(sqe, fd, len, offset, flags);
  sqe->user_data = 232;
  return uring_submit_wait_one(ctx);
}

int uring_fadvise_sync(uring_ctx *ctx, int fd, uint64_t offset, unsigned int len, int advice) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_fadvise(sqe, fd, offset, len, advice);
  sqe->user_data = 233;
  return uring_submit_wait_one(ctx);
}

int uring_madvise_sync(uring_ctx *ctx, void *addr, unsigned int length, int advice) {
  if (!ctx || !addr || length == 0) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_madvise(sqe, addr, length, advice);
  sqe->user_data = 234;
  return uring_submit_wait_one(ctx);
}

int uring_async_cancel_fd_sync(uring_ctx *ctx, int fd, unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_cancel_fd(sqe, fd, flags);
  sqe->user_data = 235;
  return uring_submit_wait_one(ctx);
}

int uring_sendmsg_iov_sync(uring_ctx *ctx, int fd, struct iovec *iov, unsigned int iovcnt, unsigned int flags) {
  if (!ctx || !iov || iovcnt == 0) {
    return -EINVAL;
  }
  struct msghdr msg;
  memset(&msg, 0, sizeof(msg));
  msg.msg_iov = iov;
  msg.msg_iovlen = (int)iovcnt;
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_sendmsg(sqe, fd, &msg, flags);
  sqe->user_data = 236;
  return uring_submit_wait_one(ctx);
}

int uring_recvmsg_iov_sync(uring_ctx *ctx, int fd, struct iovec *iov, unsigned int iovcnt, unsigned int flags) {
  if (!ctx || !iov || iovcnt == 0) {
    return -EINVAL;
  }
  struct msghdr msg;
  memset(&msg, 0, sizeof(msg));
  msg.msg_iov = iov;
  msg.msg_iovlen = (int)iovcnt;
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_recvmsg(sqe, fd, &msg, flags);
  sqe->user_data = 237;
  return uring_submit_wait_one(ctx);
}

int uring_socket_sync(uring_ctx *ctx, int domain, int type, int protocol, unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_socket(sqe, domain, type, protocol, flags);
  sqe->user_data = 238;
  return uring_submit_wait_one(ctx);
}

int uring_pipe_sync(uring_ctx *ctx, int *fds, int pipe_flags) {
  if (!ctx || !fds) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_pipe(sqe, fds, pipe_flags);
  sqe->user_data = 239;
  return uring_submit_wait_one(ctx);
}

int uring_bind_sync(uring_ctx *ctx, int fd, const struct sockaddr *addr, socklen_t addrlen) {
  if (!ctx || !addr) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_bind(sqe, fd, addr, addrlen);
  sqe->user_data = 240;
  return uring_submit_wait_one(ctx);
}

int uring_listen_sync(uring_ctx *ctx, int fd, int backlog) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_listen(sqe, fd, backlog);
  sqe->user_data = 241;
  return uring_submit_wait_one(ctx);
}

int uring_openat2_sync(uring_ctx *ctx, int dfd, const char *path, const struct open_how *how) {
  if (!ctx || !path || !how) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_openat2(sqe, dfd, path, how);
  sqe->user_data = 242;
  return uring_submit_wait_one(ctx);
}

int uring_link_timeout_sync(uring_ctx *ctx, const struct __kernel_timespec *ts, unsigned int flags) {
  if (!ctx || !ts) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_link_timeout(sqe, ts, flags);
  sqe->user_data = 243;
  return uring_submit_wait_one(ctx);
}

int uring_getxattr_sync(uring_ctx *ctx, const char *name, char *value, const char *path, unsigned int len) {
  if (!ctx || !name || !value || !path) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_getxattr(sqe, name, value, path, len);
  sqe->user_data = 244;
  return uring_submit_wait_one(ctx);
}

int uring_setxattr_sync(uring_ctx *ctx, const char *name, const char *value, const char *path, int flags,
                        unsigned int len) {
  if (!ctx || !name || !value || !path) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_setxattr(sqe, name, value, path, flags, len);
  sqe->user_data = 245;
  return uring_submit_wait_one(ctx);
}

int uring_fgetxattr_sync(uring_ctx *ctx, int fd, const char *name, char *value, unsigned int len) {
  if (!ctx || !name || !value) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_fgetxattr(sqe, fd, name, value, len);
  sqe->user_data = 246;
  return uring_submit_wait_one(ctx);
}

int uring_fsetxattr_sync(uring_ctx *ctx, int fd, const char *name, const char *value, int flags,
                         unsigned int len) {
  if (!ctx || !name || !value) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_fsetxattr(sqe, fd, name, value, flags, len);
  sqe->user_data = 247;
  return uring_submit_wait_one(ctx);
}

int uring_epoll_ctl_sync(uring_ctx *ctx, int epfd, int fd, int op, struct epoll_event *ev) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_epoll_ctl(sqe, epfd, fd, op, ev);
  sqe->user_data = 248;
  return uring_submit_wait_one(ctx);
}

int uring_provide_buffers_sync(uring_ctx *ctx, void *addr, int len, int nr, int bgid, int bid) {
  if (!ctx || !addr || len <= 0 || nr <= 0) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_provide_buffers(sqe, addr, len, nr, bgid, bid);
  sqe->user_data = 249;
  return uring_submit_wait_one(ctx);
}

int uring_remove_buffers_sync(uring_ctx *ctx, int nr, int bgid) {
  if (!ctx || nr <= 0) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_remove_buffers(sqe, nr, bgid);
  sqe->user_data = 250;
  return uring_submit_wait_one(ctx);
}

int uring_msg_ring_sync(uring_ctx *ctx, int fd, unsigned int len, uint64_t data, unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_msg_ring(sqe, fd, len, data, flags);
  sqe->user_data = 251;
  return uring_submit_wait_one(ctx);
}

int uring_ftruncate_sync(uring_ctx *ctx, int fd, long long len) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_ftruncate(sqe, fd, (loff_t)len);
  sqe->user_data = 252;
  return uring_submit_wait_one(ctx);
}

int uring_nop128_sync(uring_ctx *ctx) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_nop128(sqe);
  sqe->user_data = 260;
  return uring_submit_wait_one(ctx);
}

int uring_poll_update_sync(uring_ctx *ctx, uint64_t old_user_data, uint64_t new_user_data, unsigned int poll_mask,
                           unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_poll_update(sqe, old_user_data, new_user_data, poll_mask, flags);
  sqe->user_data = 261;
  return uring_submit_wait_one(ctx);
}

int uring_timeout_update_sync(uring_ctx *ctx, const struct __kernel_timespec *ts, uint64_t target_user_data,
                              unsigned int flags) {
  if (!ctx || !ts) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_timeout_update(sqe, ts, target_user_data, flags);
  sqe->user_data = 262;
  return uring_submit_wait_one(ctx);
}

int uring_recv_multishot_sync(uring_ctx *ctx, int sockfd, void *buf, size_t len, int msg_flags) {
  if (!ctx || (!buf && len > 0)) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_recv_multishot(sqe, sockfd, buf, len, msg_flags);
  sqe->user_data = 263;
  return uring_submit_wait_one(ctx);
}

int uring_send_zc_sync(uring_ctx *ctx, int sockfd, const void *buf, size_t len, int msg_flags, unsigned int zc_flags) {
  if (!ctx || (!buf && len > 0)) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_send_zc(sqe, sockfd, buf, len, msg_flags, zc_flags);
  sqe->user_data = 264;
  return uring_submit_wait_one(ctx);
}

int uring_send_zc_fixed_sync(uring_ctx *ctx, int sockfd, const void *buf, size_t len, int msg_flags,
                            unsigned int zc_flags, unsigned int buf_index) {
  if (!ctx || (!buf && len > 0)) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_send_zc_fixed(sqe, sockfd, buf, len, msg_flags, zc_flags, buf_index);
  sqe->user_data = 265;
  return uring_submit_wait_one(ctx);
}

int uring_sendmsg_zc_iov_sync(uring_ctx *ctx, int fd, struct iovec *iov, unsigned int iovcnt, unsigned int flags) {
  if (!ctx || !iov || iovcnt == 0) {
    return -EINVAL;
  }
  struct msghdr msg;
  memset(&msg, 0, sizeof(msg));
  msg.msg_iov = iov;
  msg.msg_iovlen = (int)iovcnt;
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_sendmsg_zc(sqe, fd, &msg, flags);
  sqe->user_data = 266;
  return uring_submit_wait_one(ctx);
}

int uring_sendmsg_zc_fixed_iov_sync(uring_ctx *ctx, int fd, struct iovec *iov, unsigned int iovcnt,
                                    unsigned int flags, unsigned int buf_index) {
  if (!ctx || !iov || iovcnt == 0) {
    return -EINVAL;
  }
  struct msghdr msg;
  memset(&msg, 0, sizeof(msg));
  msg.msg_iov = iov;
  msg.msg_iovlen = (int)iovcnt;
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_sendmsg_zc_fixed(sqe, fd, &msg, flags, buf_index);
  sqe->user_data = 267;
  return uring_submit_wait_one(ctx);
}

int uring_recv_zc_sync(uring_ctx *ctx, int fd, void *buf, unsigned int len, unsigned int msg_flags,
                       unsigned int ioprio_zc) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_rw(IORING_OP_RECV_ZC, sqe, fd, buf, len, 0);
  sqe->msg_flags = msg_flags;
  sqe->ioprio = (__u32)ioprio_zc;
  sqe->user_data = 268;
  return uring_submit_wait_one(ctx);
}

int uring_recvmsg_multishot_iov_sync(uring_ctx *ctx, int fd, struct iovec *iov, unsigned int iovcnt,
                                     unsigned int flags) {
  if (!ctx || !iov || iovcnt == 0) {
    return -EINVAL;
  }
  struct msghdr msg;
  memset(&msg, 0, sizeof(msg));
  msg.msg_iov = iov;
  msg.msg_iovlen = (int)iovcnt;
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_recvmsg_multishot(sqe, fd, &msg, flags);
  sqe->user_data = 269;
  return uring_submit_wait_one(ctx);
}

int uring_epoll_wait_sync(uring_ctx *ctx, int epfd, struct epoll_event *events, int maxevents, unsigned int flags) {
  if (!ctx || !events || maxevents <= 0) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_epoll_wait(sqe, epfd, events, maxevents, flags);
  sqe->user_data = 270;
  return uring_submit_wait_one(ctx);
}

int uring_waitid_sync(uring_ctx *ctx, int idtype, int id, siginfo_t *infop, int options, unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_waitid(sqe, (idtype_t)idtype, (id_t)id, infop, options, flags);
  sqe->user_data = 271;
  return uring_submit_wait_one(ctx);
}

int uring_futex_wake_sync(uring_ctx *ctx, const uint32_t *futex, uint64_t val, uint64_t mask, uint32_t futex_flags,
                          unsigned int flags) {
  if (!ctx || !futex) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_futex_wake(sqe, futex, val, mask, futex_flags, flags);
  sqe->user_data = 272;
  return uring_submit_wait_one(ctx);
}

int uring_futex_wait_sync(uring_ctx *ctx, const uint32_t *futex, uint64_t val, uint64_t mask, uint32_t futex_flags,
                          unsigned int flags) {
  if (!ctx || !futex) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_futex_wait(sqe, futex, val, mask, futex_flags, flags);
  sqe->user_data = 273;
  return uring_submit_wait_one(ctx);
}

int uring_futex_waitv_sync(uring_ctx *ctx, const struct futex_waitv *futex, uint32_t nr_futex, unsigned int flags) {
  if (!ctx || !futex || nr_futex == 0) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_futex_waitv(sqe, futex, nr_futex, flags);
  sqe->user_data = 274;
  return uring_submit_wait_one(ctx);
}

int uring_uring_cmd_sync(uring_ctx *ctx, int cmd_op, int fd) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_uring_cmd(sqe, cmd_op, fd);
  sqe->user_data = 275;
  return uring_submit_wait_one(ctx);
}

int uring_uring_cmd128_sync(uring_ctx *ctx, int cmd_op, int fd) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_uring_cmd128(sqe, cmd_op, fd);
  sqe->user_data = 276;
  return uring_submit_wait_one(ctx);
}

int uring_cmd_sock_sync(uring_ctx *ctx, int cmd_op, int fd, int level, int optname, void *optval, int optlen) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_cmd_sock(sqe, cmd_op, fd, level, optname, optval, optlen);
  sqe->user_data = 277;
  return uring_submit_wait_one(ctx);
}

int uring_cmd_getsockname_sync(uring_ctx *ctx, int fd, struct sockaddr *addr, socklen_t *addrlen, int peer) {
  if (!ctx || !addr || !addrlen) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_cmd_getsockname(sqe, fd, addr, addrlen, peer);
  sqe->user_data = 278;
  return uring_submit_wait_one(ctx);
}

int uring_fixed_fd_install_sync(uring_ctx *ctx, int fd, unsigned int install_flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_fixed_fd_install(sqe, fd, install_flags);
  sqe->user_data = 279;
  return uring_submit_wait_one(ctx);
}

int uring_socket_direct_sync(uring_ctx *ctx, int domain, int type, int protocol, unsigned int file_index,
                             unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_socket_direct(sqe, domain, type, protocol, file_index, flags);
  sqe->user_data = 280;
  return uring_submit_wait_one(ctx);
}

int uring_socket_direct_alloc_sync(uring_ctx *ctx, int domain, int type, int protocol, unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_socket_direct_alloc(sqe, domain, type, protocol, flags);
  sqe->user_data = 281;
  return uring_submit_wait_one(ctx);
}

int uring_pipe_direct_sync(uring_ctx *ctx, int *fds, int pipe_flags, unsigned int file_index) {
  if (!ctx || !fds) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_pipe_direct(sqe, fds, pipe_flags, file_index);
  sqe->user_data = 282;
  return uring_submit_wait_one(ctx);
}

int uring_msg_ring_fd_sync(uring_ctx *ctx, int fd, int source_fd, int target_fd, uint64_t data, unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_msg_ring_fd(sqe, fd, source_fd, target_fd, data, flags);
  sqe->user_data = 283;
  return uring_submit_wait_one(ctx);
}

int uring_msg_ring_fd_alloc_sync(uring_ctx *ctx, int fd, int source_fd, uint64_t data, unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_msg_ring_fd_alloc(sqe, fd, source_fd, data, flags);
  sqe->user_data = 284;
  return uring_submit_wait_one(ctx);
}

int uring_msg_ring_cqe_flags_sync(uring_ctx *ctx, int fd, unsigned int len, uint64_t data, unsigned int flags,
                                  unsigned int cqe_flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_msg_ring_cqe_flags(sqe, fd, len, data, flags, cqe_flags);
  sqe->user_data = 285;
  return uring_submit_wait_one(ctx);
}

int uring_files_update_sync(uring_ctx *ctx, int *fds, unsigned int nr_fds, int offset) {
  if (!ctx || (!fds && nr_fds > 0)) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_files_update(sqe, fds, nr_fds, offset);
  sqe->user_data = 286;
  return uring_submit_wait_one(ctx);
}

int uring_send_bundle_sync(uring_ctx *ctx, int sockfd, size_t len, int msg_flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_send_bundle(sqe, sockfd, len, msg_flags);
  sqe->user_data = 287;
  return uring_submit_wait_one(ctx);
}

int uring_readv_fixed_sync(uring_ctx *ctx, int fd, struct iovec *iov, unsigned int iovcnt, uint64_t offset,
                           int rw_flags, int buf_index) {
  if (!ctx || !iov || iovcnt == 0) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_readv_fixed(sqe, fd, iov, iovcnt, offset, rw_flags, buf_index);
  sqe->user_data = 288;
  return uring_submit_wait_one(ctx);
}

int uring_writev_fixed_sync(uring_ctx *ctx, int fd, struct iovec *iov, unsigned int iovcnt, uint64_t offset,
                            int rw_flags, int buf_index) {
  if (!ctx || !iov || iovcnt == 0) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_writev_fixed(sqe, fd, iov, iovcnt, offset, rw_flags, buf_index);
  sqe->user_data = 289;
  return uring_submit_wait_one(ctx);
}

int uring_sendto_sync(uring_ctx *ctx, int sockfd, const void *buf, size_t len, int msg_flags,
                      const struct sockaddr *addr, socklen_t addrlen) {
  if (!ctx || (!buf && len > 0)) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_sendto(sqe, sockfd, buf, len, msg_flags, addr, addrlen);
  sqe->user_data = 290;
  return uring_submit_wait_one(ctx);
}

int uring_timeout_sync(uring_ctx *ctx, const struct __kernel_timespec *ts, unsigned int count,
                       unsigned int timeout_flags, uint64_t user_data) {
  if (!ctx || !ts) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_timeout(sqe, ts, count, timeout_flags);
  sqe->user_data = user_data;
  return uring_submit_wait_one(ctx);
}

int uring_timeout_remove_sync(uring_ctx *ctx, uint64_t target_user_data, unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_timeout_remove(sqe, target_user_data, flags);
  sqe->user_data = 216;
  return uring_submit_wait_one(ctx);
}

int uring_async_cancel_sync(uring_ctx *ctx, uint64_t cancel_user_data, unsigned int flags) {
  if (!ctx) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe = io_uring_get_sqe(&ctx->ring);
  if (!sqe) {
    return -EAGAIN;
  }
  io_uring_prep_cancel64(sqe, cancel_user_data, (int)flags);
  sqe->user_data = 217;
  return uring_submit_wait_one(ctx);
}

// Submit read linked to write (same buffer). Waits for two CQEs; returns write result or error.
int uring_link_read_write_sync(uring_ctx *ctx, int fd_in, void *buf, unsigned len, long long off_in,
                               int fd_out, long long off_out) {
  if (!ctx || !buf || len == 0) {
    return -EINVAL;
  }
  struct io_uring_sqe *sqe1 = io_uring_get_sqe(&ctx->ring);
  struct io_uring_sqe *sqe2 = io_uring_get_sqe(&ctx->ring);
  if (!sqe1 || !sqe2) {
    return -EAGAIN;
  }
  io_uring_prep_read(sqe1, fd_in, buf, len, (off_t)off_in);
  sqe1->user_data = 301;
  sqe1->flags |= IOSQE_IO_LINK;

  io_uring_prep_write(sqe2, fd_out, buf, len, (off_t)off_out);
  sqe2->user_data = 302;

  int ret = io_uring_submit(&ctx->ring);
  if (ret < 0) {
    return ret;
  }
  for (int i = 0; i < 2; i++) {
    struct io_uring_cqe *cqe = NULL;
    ret = io_uring_wait_cqe(&ctx->ring, &cqe);
    if (ret < 0) {
      return ret;
    }
    int res = cqe->res;
    uint64_t ud = cqe->user_data;
    io_uring_cqe_seen(&ctx->ring, cqe);
    if (res < 0) {
      return res;
    }
    if (i == 1 && ud == 302) {
      return res;
    }
  }
  return -EIO;
}

uint64_t uring_statx_stx_size(const struct statx *sx) {
  if (!sx) {
    return 0;
  }
  return (uint64_t)sx->stx_size;
}

// Submit a long timeout then its removal in one submit; wait for two CQEs (cancels the sleep).
int uring_timeout_arm_remove_pair_sync(uring_ctx *ctx, int64_t sec, int64_t nsec, uint64_t timeout_user_data) {
  if (!ctx) {
    return -EINVAL;
  }
  struct __kernel_timespec ts;
  memset(&ts, 0, sizeof(ts));
  ts.tv_sec = sec;
  ts.tv_nsec = nsec;

  struct io_uring_sqe *t = io_uring_get_sqe(&ctx->ring);
  if (!t) {
    return -EAGAIN;
  }
  io_uring_prep_timeout(t, &ts, 0, 0);
  t->user_data = timeout_user_data;

  struct io_uring_sqe *r = io_uring_get_sqe(&ctx->ring);
  if (!r) {
    return -EAGAIN;
  }
  io_uring_prep_timeout_remove(r, timeout_user_data, 0);
  r->user_data = timeout_user_data + 1;

  int ret = io_uring_submit(&ctx->ring);
  if (ret < 0) {
    return ret;
  }
  for (int i = 0; i < 2; i++) {
    struct io_uring_cqe *cqe = NULL;
    ret = io_uring_wait_cqe(&ctx->ring, &cqe);
    if (ret < 0) {
      return ret;
    }
    int res = cqe->res;
    io_uring_cqe_seen(&ctx->ring, cqe);
    /* Timeout op may complete with -ETIME; remove/cancel paths may use -ECANCELED. */
    if (res < 0 && res != -ETIME && res != -ECANCELED) {
      return res;
    }
  }
  return 0;
}

