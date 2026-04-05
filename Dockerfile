FROM python:3.12-slim

ARG REQUIREMENTS=requirements.txt

RUN apt update && apt install -y ffmpeg curl

WORKDIR /app

COPY requirements*.txt ./
RUN pip install --no-cache-dir -r ${REQUIREMENTS}

COPY . .
