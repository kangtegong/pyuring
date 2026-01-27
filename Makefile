CC ?= gcc
CFLAGS ?= -O2 -g -Wall -Wextra -fPIC
LDFLAGS ?=

LIB_NAME := liburingwrap.so
SRC := csrc/uring_wrap.c csrc/bench_direct.c
OUT := build/$(LIB_NAME)

LOCAL_LIBURING_DIR := third_party/liburing
LOCAL_LIBURING_INC := $(LOCAL_LIBURING_DIR)/src/include
LOCAL_LIBURING_A := $(LOCAL_LIBURING_DIR)/src/liburing.a
LOCAL_LIBURING_H := $(LOCAL_LIBURING_INC)/liburing.h

# If liburing isn't installed system-wide (no sudo), you can vendor it:
#   make fetch-liburing
#   make
ifeq ($(wildcard $(LOCAL_LIBURING_H)),)
  URING_CFLAGS :=
  URING_LIBS := -luring
  URING_DEPS :=
else
  URING_CFLAGS := -I$(LOCAL_LIBURING_INC)
  URING_LIBS := $(LOCAL_LIBURING_A)
  URING_DEPS := $(LOCAL_LIBURING_A)
endif

.PHONY: all clean

all: $(OUT)

build:
	mkdir -p build

$(OUT): build $(SRC) $(URING_DEPS)
	$(CC) $(CFLAGS) $(URING_CFLAGS) -shared -o $(OUT) $(SRC) $(URING_LIBS) $(LDFLAGS)

.PHONY: fetch-liburing liburing

fetch-liburing:
	mkdir -p third_party
	if [ ! -d "$(LOCAL_LIBURING_DIR)/.git" ]; then \
	  git clone --depth 1 https://github.com/axboe/liburing.git "$(LOCAL_LIBURING_DIR)"; \
	fi

liburing: fetch-liburing
	$(MAKE) -C "$(LOCAL_LIBURING_DIR)"

$(LOCAL_LIBURING_A): fetch-liburing
	$(MAKE) -C "$(LOCAL_LIBURING_DIR)"

clean:
	rm -rf build


