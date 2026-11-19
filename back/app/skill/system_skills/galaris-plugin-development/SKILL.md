---
name: galaris-plugin-development
description: Design, build and qualify plugins for Galaris. Use when asked to deliver a signed Service preset or data template, or to implement a supported document format, AI provider, preview converter or file-sharing protocol.
---

# Develop a Galaris plugin

Work from the requested integration and target Galaris version. Choose the smallest supported
contribution. A signed plugin can deliver a Service preset that uses an existing REST or MCP
protocol, a downloadable JSON data template, a binary document format with a browser editor,
an AI provider profile, an attachment preview converter or a file-sharing protocol. Other
extension points may require changes to the host. Verify the loader contract before promising
an installable ZIP.

## Read the installed contract

Use `documentation_catalog` and `documentation_search` when available. Read the relevant
guides with `file_read`, continuing at `next_offset` as needed:

- `galaris://documentation/docs/en/dev/plugin-authoring.md` for selecting a Sample, preparing
  a source directory and packaging it.
- `galaris://documentation/docs/en/dev/plugin-bundles.md` for manifest fields, trust and the
  entry points of executable contributions.
- `galaris://documentation/docs/en/dev/plugin-api.md` for preview, install, activate and remove,
  with request examples.
- `galaris://documentation/docs/en/dev/document-formats.md` and
  `galaris://documentation/docs/en/dev/document-references.md` for a document format or an
  editor that composes Link, Card and Embed. Use the public host components and advertise only
  the surfaces the format can render. Keep original bytes, access checks and revisions under
  Documents. Save with the revision observed by the editor and keep drafts after failures.

The same paths under `docs/fr` provide French guides. With an authorized checkout, use the
matching implementation in `plugins/sample/` and its tests. Documentation access does not give
access to checkout files. If the checkout is absent, use the inline examples in the guides.

## Produce the deliverable

1. Identify the publisher-qualified code, release version, compatible host range and contribution
   codes. Use manifest version 1 for Service presets alone and version 2 for other families.
   Keep labels and descriptions in French and English. Put endpoints and account values in
   standard Connection parameters. Exclude credentials and private keys from source and ZIP.
2. Write the manifest, contribution files and tests into the authorized workspace. If a shell
   and the packager are available, build with `python -m plugins.sample.package build`. It fills
   in payload hashes and signs the exact manifest bytes with the publisher's Ed25519 key.
   Use only an authorized signing environment and key. When signing is unavailable, deliver
   the source and reproducible commands for the publisher. Label an unsigned package as source.
3. Use synthetic fixtures on the target version. Verify the contribution through its real
   entry point, permissions, compatibility, activation and withdrawal. For document plugins,
   also verify reload, revision conflict, read-only use, snapshots and access to the source
   after removal. Report which checks ran and the ZIP SHA-256 if a signed bundle exists.

This skill provides authoring instructions. Check the effective tools before writing files,
running commands or calling an API. There is no native plugin-management MCP tool. Use the
administration API or UI only with an authorized identity and within the requested change.
Publisher trust, executable trust, installation, activation and catalogue publication are
operator actions. Keep those decisions separate from creating the source or bundle.
