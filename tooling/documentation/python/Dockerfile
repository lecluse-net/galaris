FROM python:3.14-slim-trixie@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
COPY requirements.txt /tooling/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r /tooling/requirements.txt
WORKDIR /repo
