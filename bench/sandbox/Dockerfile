FROM node:22.18.0-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin bench \
    && mkdir -p /workspace \
    && chown bench:bench /workspace

WORKDIR /workspace
USER bench
