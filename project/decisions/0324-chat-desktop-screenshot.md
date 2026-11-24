# 0324 — One-shot desktop screenshots in Chat

Status: accepted for implementation.

`chat_screenshot` is a first-party Chat tool scoped to a live internal text turn
sent by a known desktop tab and an active web session family. Each screenshot
requires deliberate local selection, preview, and confirmation. Conversation
merges preserve this ability only when all admitted messages have the same
verified desktop origin. Agent Tasks and the public agent MCP access cannot mount it.

The desktop uses outbound HTTPS over the existing Galaris origin. The Chat
service owns presence, request delivery, single-use replies, and expiry. Chat
uses the public Services MCP contract and the File Sharing facade. Consuming an
approved upload in a current turn saves the image as a managed file private to
the agent. The tool returns the canonical `file://<uuid>` URI and file metadata
for attachments. The transient encrypted reply is removed on consumption or
expiry.
