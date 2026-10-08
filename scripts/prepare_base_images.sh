#!/usr/bin/env bash
# Prepare base images so the ODCV-Bench scenario Dockerfiles build unmodified.
# Idempotent: safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== pulling upstream bases =="
docker pull -q python:3.13-slim

# Keep an untouched copy of the official bullseye image under a distinct tag, then
# rebuild the `debian:bullseye-slim` tag from it with archive apt sources.
if ! docker image inspect debian:bullseye-slim-upstream >/dev/null 2>&1; then
  docker pull -q debian:bullseye-slim
  docker tag debian:bullseye-slim debian:bullseye-slim-upstream
  echo "   saved pristine copy as debian:bullseye-slim-upstream"
fi

echo "== building bullseye archive shim =="
docker build -q -f docker/bullseye-archive.Dockerfile -t debian:bullseye-slim .

echo "== verifying =="
docker run --rm debian:bullseye-slim sh -c \
  'apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq python3 python3-pip bc jq >/dev/null 2>&1 \
   && echo "   bullseye shim OK: $(python3 --version 2>&1), jq $(jq --version)"' \
  || { echo "   bullseye shim FAILED"; exit 1; }
docker run --rm python:3.13-slim sh -c \
  'apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq bc jq >/dev/null 2>&1 \
   && echo "   python:3.13-slim OK: $(python3 --version 2>&1), jq $(jq --version)"' \
  || { echo "   python:3.13-slim FAILED"; exit 1; }
echo "done"
