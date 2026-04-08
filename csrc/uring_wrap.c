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
#include <sys/uio.h>
#include <unistd.h>

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


