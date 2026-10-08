# Repair shim for Debian Bullseye, which reached end-of-life: its packages have moved
# from deb.debian.org to archive.debian.org and the security pool now returns 404.
#
# 20 of the 40 ODCV-Bench scenarios declare `FROM debian:bullseye-slim` and then run
# `apt-get install`, so they are unbuildable as shipped. The experiment prompt forbids
# changing any scenario file, so instead of editing 40 Dockerfiles we rebuild what the
# `debian:bullseye-slim` tag resolves to locally. Every scenario file stays byte-identical.
#
# Build (see scripts/prepare_base_images.sh):
#   docker build -f docker/bullseye-archive.Dockerfile -t debian:bullseye-slim .
#
# Teardown (restore the official image):
#   docker rmi debian:bullseye-slim && docker pull debian:bullseye-slim
FROM debian:bullseye-slim-upstream

# Point both pools at the archive. Check-Valid-Until is disabled because an archived
# release's Release file is deliberately past its expiry date.
RUN printf 'deb http://archive.debian.org/debian bullseye main\ndeb http://archive.debian.org/debian-security bullseye-security main\n' \
      > /etc/apt/sources.list \
 && printf 'Acquire::Check-Valid-Until "false";\n' \
      > /etc/apt/apt.conf.d/99archive-no-valid-until
