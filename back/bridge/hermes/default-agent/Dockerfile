ARG HERMES_IMAGE=nousresearch/hermes-agent:v0.22.4@sha256:7a69201726bc64db2072a1371557137c23312d29705cda2b8ea2a0214a50a4cf
FROM ${HERMES_IMAGE}

COPY patch_run_stop.py.txt /tmp/galaris-patch-run-stop.py
COPY galaris_authorization.py.txt /opt/hermes/galaris_authorization.py
COPY runtime_support.py /opt/hermes/runtime_support.py
RUN python /tmp/galaris-patch-run-stop.py && rm /tmp/galaris-patch-run-stop.py

# One image recipe per Harness provider. Agent-specific configuration, skills and
# workspace remain mounted at runtime and never create additional agent containers.
LABEL org.galaris.harness="hermes"
