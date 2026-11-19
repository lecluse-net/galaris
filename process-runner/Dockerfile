ARG PYTHON_IMAGE=python:3.14-slim-trixie@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
ARG DOCKER_CLI_IMAGE=docker:29-cli@sha256:34507eb5069d8be82c95dd3b6987d4250fd5fee49b82e2509b7d7a7030740d6d
FROM ${DOCKER_CLI_IMAGE} AS docker-cli
FROM ${PYTHON_IMAGE} AS python

FROM python AS sandbox-files
RUN mkdir /runtime && rm -rf /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/ensurepip \
    && find /usr/local/lib/python3.14/lib-dynload -name '*.so' -exec ldd {} \; > /tmp/libs \
    && ldd /usr/local/bin/python3.14 >> /tmp/libs \
    && awk '/=> \// {print $3} /^[[:space:]]*\// {print $1}' /tmp/libs | sort -u | xargs -r cp -L --parents -t /runtime

FROM scratch AS sandbox
COPY --from=sandbox-files /runtime/ /
COPY --from=python /usr/local/bin/python3.14 /usr/local/bin/python3.14
COPY --from=python /usr/local/lib/libpython3.14.so.1.0 /usr/local/lib/libpython3.14.so.1.0
COPY --from=sandbox-files /usr/local/lib/python3.14 /usr/local/lib/python3.14
COPY sandbox.py /sandbox.py
ENV LD_LIBRARY_PATH=/usr/local/lib
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/python3.14", "-IBu", "/sandbox.py"]

FROM python AS supervisor
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY supervisor.py /supervisor.py
ENTRYPOINT ["/usr/local/bin/python3.14", "-IBu", "/supervisor.py"]
