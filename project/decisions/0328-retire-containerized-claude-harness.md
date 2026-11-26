# 0328 — Retire the containerized Claude harness

Status: Accepted

Claude Agent is supplied by the backend's embedded SDK. The agent selector uses
the names Pydantic AI, Claude Agent, DeepSeek Agent and Codex for the standard
harnesses. Hermes is an explicit opt-in on new installations. Other explicitly
configured harnesses keep their stored assignments and names.

The retired Claude provider is invisible to the catalogue and cannot provision a
runtime. Existing assignments remain readable and executable during the transition,
and DbAdmin retains them. After open tasks finish, switching to Claude Agent uses
the existing managed-runtime cleanup and token revocation. The original runtime
template remains available for isolated qualification.
