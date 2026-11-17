FROM python:3.14-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f
COPY audit.py /tooling/audit.py
COPY test_audit.py /tooling/test_audit.py
WORKDIR /tooling
ENTRYPOINT ["python", "/tooling/audit.py"]
