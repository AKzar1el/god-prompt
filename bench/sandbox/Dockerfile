FROM node:22.18.0-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
