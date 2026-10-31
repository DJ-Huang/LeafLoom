# Build the ARM64 image on an ARM64 Docker host; use --platform for other NASes.
FROM rust:alpine@sha256:7e9e2d068a107a2adafd19930011178d14a78326053cd4c3a9f7ad3fd049557d AS builder
RUN apk add --no-cache musl-dev patch
WORKDIR /src
# v0.47.0, upstream commit 225f2542670d8f5a58a9f5fe918791f0987759c8.
ADD --checksum=sha256:bab9d4fa1654adc6c88523b61bb8697f575334248cf554282e1f87e2329c0569 https://codeload.github.com/sigoden/dufs/tar.gz/refs/tags/v0.47.0 /tmp/dufs.tar.gz
RUN tar -xzf /tmp/dufs.tar.gz --strip-components=1
COPY no-symlinks.patch /tmp/no-symlinks.patch
RUN patch -p1 < /tmp/no-symlinks.patch && cargo build --release --locked -j 2

FROM scratch
COPY --from=builder /src/target/release/dufs /bin/dufs
LABEL org.opencontainers.image.title="DUFS with LeafLoom strict symlink checks" \
      org.opencontainers.image.version="0.47.0-leafloom.1" \
      org.opencontainers.image.source="https://github.com/sigoden/dufs" \
      org.opencontainers.image.revision="225f2542670d8f5a58a9f5fe918791f0987759c8" \
      org.opencontainers.image.licenses="MIT OR Apache-2.0"
STOPSIGNAL SIGINT
ENTRYPOINT ["/bin/dufs"]
