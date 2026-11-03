# 0264 — Supported LTS runtimes and artifact-scoped kernel-header assessment

Status: accepted. Date: 2026-11-03. Refines [0263](0263-security-only-release-gate.md).

## Problem and decision

The 0.3.1 gate correctly rejected unpatched OpenSSH and libxml2 in Debian stable.
Rebuilding and upgrading that distribution did not provide their fixes. Backend
and SSH images now use the official Ubuntu 26.04 LTS image pinned by digest and
receive its security updates. Python remains 3.14. PostgreSQL clients remain 17
from the signed official PGDG repository, with its public key pinned by checksum
and verified against the published fingerprint. No server or data format upgrade
is introduced. Compilers remain available in SSH for existing managed editor and
native extension installation; backend compilers stay in builder stages.

The browser executor uses Chromium only. Remove the two vulnerable GStreamer Bad
packages supplied for unused WebKit support. Preserve actual navigation, PDF,
SVG, 3D thumbnail and network isolation behavior through the real browser tests.

Trivy 0.76.1 replaces 0.74.0. Every HIGH/CRITICAL finding is printed with package,
version, CVE, status, severity source, fixed version and advisory URL. Raw JSON
inventories remain available even when the gate fails. Unfixed runtime findings
still block; no blanket `ignore-unfixed`, package-wide or severity downgrade is used.

## Kernel-header assessment

After the OS fixes, the SSH image's remaining findings concern kernel code mapped
to the binary package `linux-libc-dev` by source-package advisories. The reviewed
62 CVEs concern kernel implementations in filesystems, drivers, networking, KVM,
crypto and kernel memory lifetime. Their implementation is not shipped by the
UAPI header package. This is an artifact assessment, not a claim that host kernels
are safe or that every future header-related finding is inapplicable.

`security/ssh-kernel-headers.openvex.json` names each reviewed CVE and the exact
Ubuntu package version, architecture and distribution. It expires on 2026-12-03.
Only the identified Galaris SSH image can apply it. Before classification, the
gate runs `security/verify-kernel-headers.py` against the immutable image ID from
the saved scan: package files must be non-executable headers/documentation and
no kernel image, source, implementation headers or modules may be installed.
The verification runs read-only, without network, capabilities or application
volumes. Invalid or missing proof, expired review and scanner errors block.

Keep raw, assessed and proof reports separately. Trivy retains every classified
finding in `ExperimentalModifiedFindings` with `not_affected` and
`vulnerable_code_not_present`; the gate verifies complete correspondence with the
raw inventory and the approved CVE/package tuples. Unknown CVEs, new versions,
other packages or other images remain blocking. No finding may disappear merely
because the scanner returned an incomplete assessment.

## Verification and limits

Release-gate scenarios use synthetic image findings to exercise runtime alerts
with and without fixes, missing inventories, classification scope, failed proof,
review expiry and lost findings. The real Trivy executable verifies native VEX
matching against an actual SSH image. A mounted synthetic kernel file makes the
real payload verification fail. Browser and SSH tests run in the final images;
populated 0.2.0 upgrade and coordinated restore exercise the new backend runtime.

Counts are scan-time evidence, never a promise that future advisories cannot
block. The release still requires successful exact-commit Security and a fresh
source scan. Host-kernel patching remains an installation responsibility.

Primary references: [Debian OpenSSH](https://security-tracker.debian.org/tracker/CVE-2026-60002),
[Debian libxml2](https://security-tracker.debian.org/tracker/CVE-2026-6653),
[Ubuntu OpenSSH fix](https://ubuntu.com/security/CVE-2026-60002),
[Ubuntu GStreamer advisory](https://ubuntu.com/security/CVE-2025-3887),
[Ubuntu UAPI file list](https://packages.ubuntu.com/resolute/amd64/linux-libc-dev/filelist),
[Trivy source/binary package limitation](https://github.com/aquasecurity/trivy/discussions/6562),
[Trivy OpenVEX matching](https://trivy.dev/docs/v0.76/guide/supply-chain/vex/file/).
