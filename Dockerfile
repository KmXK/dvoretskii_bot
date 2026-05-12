# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ARG REQUIREMENTS=requirements.txt

RUN rm -f /etc/apt/apt.conf.d/docker-clean

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl fonts-dejavu-core

WORKDIR /app

COPY requirements*.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r ${REQUIREMENTS}

COPY . .
