<p align="right"><a href="../../../fr/architecture/flows/media-resources.md">Français</a> · <strong>English</strong></p>

# Media and Resource Flow

Document and discussion thumbnails share `core.preview.thumbnails`. Each canonical URL/URI
maps to one SHA-256 key and a PNG file directly under `GALARIS_THUMBNAIL_ROOT`, with optional
page metadata in a JSON file under the same key. Images fit within 520 × 320, preserving
aspect ratio and transparency without padding. HTML uses the shared browser renderer;
`.url` shortcuts reuse their target URL's thumbnail. Each domain checks access before
reading the cache. Deleting a shortcut does not delete its target's preview.

Galaris separates a resource's canonical identity, its bounded transfer, and the strictly technical temporary files required by certain libraries.

## Source search

`search_web` calls SearXNG through asynchronous HTTP with a client owned by the call:
network waits and cancellation do not block other conversations' event loop. The normalized
response retains useful sources alongside provider coverage limitations. Unavailable engines
or unreadable entries produce a degraded search while preserving partial results; they do not
establish that relevant sources do not exist. An invalid envelope, timeout or HTTP rejection
is a distinct search failure. Diagnostics copy neither queries, response bodies nor raw exceptions.

The query, result order and `SEARCH_DEFAULT_LANGUAGE` are preserved. Diagnostic language does
not implicitly change engine language. No lexical relevance filter is applied.
`SearchClient.search()` keeps its list for synchronous consumers; `search_response()` and
`asearch_response()` also expose coverage limitations. Search, Browser and HTTPS file transport
remain separate capabilities.

## Browser sessions and tool authorization

Executor error codes are restricted to the public protocol. Invalid envelopes or unknown
codes become `executor_failed`, without copying external messages or signed URLs.
An expired session remains an explicit failure; its action is not replayed in a new
session. The agent may explicitly open a new navigation session.

Every native call rechecks the current authorization projection before its effect, even
when its MCP server predates a revocation. Reactivation permits an already mounted function
to run again; it does not implicitly mount new functions in the run.

## Incoming Attachment

```text
Canonical attachment
  → <tool.code>://<room-locator-provider>/<attachment-uuid-local>
  → prompt and tools with this exact URI
  → bounded temporary materialization only if a consumer requires bytes
  → deletion of the temporary file
```

Input staging never changes the identity presented to the model. The internal harness may download an image or document into a temporary file in order to construct a multimodal input, but this path is neither addressable by the agent, nor durable, nor recorded in the Working
Set. Media not transmitted natively remains with the provider and is consumed through its URI.

`console://` exists only when a console is attached to the run and designates its home. Without a console, no local filesystem is announced: the agent can manipulate only resources from the current Messenger and file-share-compatible providers returned by
`file_schemes`. Creation then requires an explicit provider destination.

For Hermes, the bridge streams binaries over the `raw` channel of the generic harness manager to this agent's instance volume. It never uses `/api/files`, whose Hermes limit of 100 MiB is not part of the Galaris contract. Messaging-channel or media-domain limits still apply; the runtime's internal transport does not add a fixed limit.

## Outgoing Attachment

`MessengerFileTransport` resolves a room or direct recipient, then delegates to the
`Messenger`. An attachment search is bounded to recent history. Bridges that support large files override upload/download to stream the bytes.

For a conversational resend request, the server first resolves the canonical `local_id` of the attachment in the authorized session, retrieves its bytes through the Messenger façade, verifies the announced and actual sizes, then uploads them to the same room. The file is neither regenerated nor converted, and no production Task is allowed for this operation.

In a Task, each produced file is registered with the exact URI of the provider that owns it.
A successful delivery preserves the source, the final artifact at the destination provider, and a receipt (tool, destination, and source). Messenger sending is an outgoing copy and never deletes the source. File labels and names remain untrusted data; only identifiers and references validated by the server are reinjected into subsequent steps.

## Resource URIs

For a staged copy, a source download failure precedes any upload and is reported to the harness
as a rejection with no destination effect. The agent can correct the source and continue.
Once uploading begins, or during direct streaming, an error retains an uncertain outcome and
prevents blind replay. The staging file is removed in either case.

The reference exchanged between tools, Tasks, and providers is canonical: `console://path`,
`<code-tool>://room-provider/attachment-uuid`, `memory://uuid`, `document://uuid`,
`document://uuid/attachments/attachment-uuid`,
`galaris://process/workflow-id`, `galaris://skill/skill-code/SKILL.md`, `https://host/path`, or
`<code-tool>://locator`. `file_schemes`
and the other `file_*` functions belong to the built-in `file_sharing` Tool, even for the
`galaris://` provider. `file_schemes` announces the effective capabilities, `file_write` writes complete UTF-8 or base64-encoded binary content, and `file_copy` streams between two schemes. Relative paths and former implicit local schemes are rejected: no implicit conversion chooses storage on behalf of the agent.
The `galaris://` provider exposes only name and text search; semantic search belongs to `memory://`. A copy from `galaris://`, `memory://`, or `document://`
uses the file's general binary limit rather than the limit for a single text write.

AFFiNE images and attachments use `<tool-code>://<workspace-id>/<blob-key>`:
the key comes from the block's `sourceId`, and the workspace belongs to the source document.
The `<workspace-id>/blob/<blob-key>` and `<workspace-id>/blobs/<blob-key>` variants
are accepted; `blob/<blob-key>` alone does not identify a workspace.
The bridge checks remote access and metadata for `file_info` and rejects application HTML
returned with HTTP 200 instead of a blob. HTML files explicitly served as attachments
remain downloadable.

A collection destination of `file_copy` or `file_move` preserves the source name. Provider metadata makes it possible to recognize an existing directory even when the caller omits the trailing `/`. A provider space such as an AFFiNE workspace or a Messenger room is likewise completed with the source name; `/` remains necessary to unambiguously declare a collection that does not yet exist. A move rejects, before copying, any source that the generic façade cannot delete, so as never to produce a partial move presented as a failure.

The preserved name is that of the source `ResourceDescriptor`, not necessarily the last segment of the locator: an attachment addressed by UUID thus retains its actual name. Specialized image, audio, and Messenger tools also receive canonical URIs. If they require a local path, they call `materialize_resource` into a bounded temporary file that they delete after the call. A `nextcloud://`, `console://`, HTTPS, Mail, or Messenger URI is therefore consumed directly. Outputs are written by `resource_create`/`resource_write`
and expose the canonical URI that was created or delivered.

`console://` always designates the SSH user's home. The forms `~/path`, the absolute home path, and its form without a slash after URI parsing are rebased to this home; they are never concatenated a second time onto the root path. No virtual `main/` segment is added:
`console://mon_fichier` reads or writes exactly `~/mon_fichier`.
Agents manage only announced local storage: `console://` when available. Multimodal staging and specialized materializations remain server-side temporary files that are cleaned up, with no URI and no persistence after the call.

Filenames carry no identity. An attachment is resolved by its UUID in the authorized room; a document by its UUID and ACLs; an external provider by an active agent connection. HTTPS URLs are read-only and their network destination is revalidated on every redirect. `http://` is never downloaded.

A document's attachments form the collection
`document://<document-uuid>/attachments/`. `file_list`, `file_info`, `file_read`, and specialized tools that materialize a URI require read permission on the parent document. `file_create`, `file_copy` to this collection, and `file_delete` require write permission on it. A document attachment is immutable: replacing it consists of creating a new one and then, if necessary, deleting the old one. These mutations create no content revision of the document.

Chat and internal Tasks share native attachment preparation: current messages first, then recent
history, deduplicated by URI. Media stays with its original message; files from an assistant
message follow it immediately with explicit provenance. `app.file_share` rechecks access and
metadata on each new run. Temporary files disappear before inference, including on failure or
cancellation. Checkpoint resume reuses its multimodal history without adding duplicate files.

Admission intersects model `input_*` flags with transport formats. PNG/JPEG/WebP/GIF and PDF use
the SDK; WAV/MP3 audio uses Chat Completions. OpenRouter additionally declares AIFF/AAC/OGG/FLAC/M4A
audio and MP4/MPEG/MOV/WebM video. Other video transports, unknown formats and unavailable files
remain explicit references. Hermes retains its text/image transport and existing fallbacks.

During model discovery, an absent modality stays unknown until catalog enrichment. Chat defaults
must not fabricate image, file, audio or video refusals; explicit provider values take precedence.
The API exposes known modalities separately from booleans filled with response defaults.

Reading a catalog never changes configured models. In the model editor, “Refresh capabilities”
reloads metadata and previews differences. “Apply to form”, followed by saving the resource,
makes those choices effective. Unknown modalities keep their saved values. Prices, context limits
and other settings are preserved. Newly created models use the discovered capabilities directly.
No schema change or automatic migration is required.

`PYDANTIC_AI_BINARY_INPUT_MAX_BYTES` bounds the total unique native bytes per run (20,000,000 by
default), prioritizing current messages. Unsupported, oversized or inaccessible files carry an
explicit notice. `image_read`, `audio_read`, `video_read`, `audio_transcribe` and appropriate file
readers remain available with their existing effects, including image descriptions in Memory.
A URI alone is never treated as already observed content. Automatic STT is skipped only for
audio whose format and declared size qualify for native input. Preflight counting reserves an
approximate 4096 tokens per media item instead of counting base64 as prose; actual consumption
comes from the provider's reported usage.

In history, an attachment remains nested in the message that transported it and exposes its URI constructed with the exact Tool code, the room's provider locator, and the file's local UUID. The projection provided to runtimes prefixes the message with its posting timestamp, sender, and human or AI nature; this rule applies to conversational executions, Tasks, and audio-turn history. Messenger and file-share are capabilities and create no schemes. File-only messages are not eliminated by session or runtime projections.

## Voice Notes

The common normalization:

1. verifies the source size;
2. requires an audio track;
3. limits the duration both by metadata and by the number of decoded samples;
4. transcodes to mono 48 kHz OGG/Opus;
5. verifies the output size;
6. always deletes the temporary file.

The common size limit comes from `MESSENGER_CONTENT_MAX_MB`, expressed in decimal megabytes
(1 MB = 1,000,000 bytes), is 1,000 MB by default, and cannot exceed this value. It applies to attachments as well as voice notes. The duration
of voice notes remains bounded separately, in minutes, by
`MESSENGER_VOICE_MAX_DURATION_MINUTES`.

## Security Invariants

- Reject `..`, injected separators, and paths escaping the root.
- Bound size, duration, history, and the number of listed entries.
- Do not infer security from a file extension alone.
- Do not log secrets or binary content.
- Clean up temporary files in a `finally` block or after a stream failure.
- Test isolation between two agents and symbolic links/path traversal.

Entry points: `back/app/file_share/resource_uri.py`, `resource_service.py`,
`messenger_transport.py`, and `back/app/messenger/media.py`.
