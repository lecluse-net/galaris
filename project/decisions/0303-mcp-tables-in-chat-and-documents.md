# 0303 — MCP tables in Chat and Text Documents

Date: 2026-11-19

Status: Accepted

Internal text conversations can present a bounded table supplied as
`structuredContent.table` by an external Streamable HTTP MCP tool. A completed
response journals the initial table with its source on the canonical Messenger
message. Opening chat history reads that snapshot. A filter changes the current
view for the reader. Insertion into a Text Document saves the displayed rows
and source as editable HTML through the document editor and its revision checks.

A table with a declared MCP Apps UI may open that resource on demand. Chat
checks the current human room access and reads the reference from the stored
message. Services verifies the original connection, tool and declared UI before
remote calls. The initial host handles a self-contained HTML form in an isolated
frame and permits read-only calls to the same enabled tool. The live form
belongs to the conversation. Its document snapshot remains usable in readers
and exports after the connection is withdrawn.
