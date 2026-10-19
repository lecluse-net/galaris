# 0208 — Task reasoning progress and Dataset edit coordinates

Date: 2026-10-19
Status: accepted

## Context

Reasoning fragments use tool-typed trace messages. Treating each fragment as a completed
tool forced repeated full Task saves and made tool usage grow with token count. Dataset
reads used character offsets while edits required line numbers, encouraging manual counting.

## Decision

Apply the existing intermediate-save cadence to text and reasoning fragments. Actual tool
events, failures and block completions remain immediate. Record one tool-usage occurrence
per semantic stream, preserving repeated invocations of the same tool.

Dataset reads retain exact JSON and character pagination, adding one-based line coordinates
and flags for partial boundary lines. Empty pages have no line coordinates. Edits retain
revision and permission checks and preserve LF, CRLF and CR endings.

## Verification

Synthetic streaming scenarios cover bursts of 9 and 2,048 fragments, block completion,
tool results and argument-generation activity. PostgreSQL scenarios cover edits located
from partial reads, neighboring content, line endings, empty pages, conflicts and denials.
