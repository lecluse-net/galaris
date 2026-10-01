ARG HERMES_IMAGE=nousresearch/hermes-agent:v2026.9.14@sha256:99641e57ec762c59e54cb44aa6746b7fc68c18b3c5ddb088af54234c613d9294
FROM ${HERMES_IMAGE}

COPY patch_run_stop.py.txt /tmp/galaris-patch-run-stop.py
COPY galaris_authorization.py.txt /opt/hermes/galaris_authorization.py
COPY runtime_support.py /opt/hermes/runtime_support.py
RUN python /tmp/galaris-patch-run-stop.py && rm /tmp/galaris-patch-run-stop.py

# One image recipe per Harness provider. Agent-specific configuration, skills and
# workspace remain mounted at runtime and never create additional agent containers.
LABEL org.galaris.harness="hermes"
