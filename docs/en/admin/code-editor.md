<p align="right"><a href="../../fr/admin/code-editor.md">Français</a> · <strong>English</strong></p>

# Configure the conversational code editor

`code-executor` supervises code-server 4.141.0, with its image and digest pinned in
`code-executor/Dockerfile`. The backend gateway serves `/api/code/gateway/` on the
same URL as Galaris and revalidates HTTP and WebSocket sessions. Do not publish the
broker on 8766 or the code-server Unix sockets.

## Origins and access

`APP_HOST` is the sole public origin, such as `https://galaris.example.net`.
No subdomain, public IDE port or `CODE_EDITOR_ORIGIN` setting is required.
In production, Nginx forwards `/api/code/gateway/` requests and WebSockets to the backend,
preserving the external Host and protocol. This route retains IDE headers without
inheriting the shell CSP or application static-file handling.
In development (exactly `APP_ENV=dev`), Vite provides the same routing;
`APP_HOST=http://localhost:8484` works. Other labels require HTTPS for the editor.

The IDE cookie is scoped to its session path and remains HttpOnly, `SameSite=Strict`
and Secure over HTTPS. The gateway filters application cookies and bearer credentials
before contacting code-server. The shell and IDE nevertheless share a browser origin:
code-server and its frontend extensions belong to the same trust boundary as the shell.
Repository and process isolation remains enforced by the broker and Linux namespaces.
Apply changes through the usual update procedure after preparing configuration and
documentation, on explicit request.

Assign `CODE_ACCESS` to the relevant human roles. The agent’s owner and the agent each
receive an explicit grant on a newly presented workspace. Existing grants remain distinct
from Chat and Agent permissions; the pane provides no sharing management. Launch tickets last 60 seconds,
are single-use and travel in URL fragments. IDE cookies are session-scoped, HttpOnly,
Secure over HTTPS and bound to the browser login family.

## Embedded Console

The broker accesses `ssh-executor` volumes over a private network, with an independent
credential initialized by `code-secrets`. Each IDE process receives only its approved
checkout, Git metadata and profile. Editable sessions receive read-only mounts of the
Unix account’s `.gitconfig`, `.config/git` and `.ssh`. Other repositories, Galaris secrets
and the Docker socket are not mounted in editors.

The launcher is trusted: Bubblewrap uses Linux namespaces, non-system identities and
no capabilities in editors. Compose’s seccomp, AppArmor and systempaths exceptions
apply to the broker. The Linux host must permit user namespaces. Unsupported hosts
report the IDE unavailable; a visual setting cannot substitute for read-only confinement.
Agent Console SSH forwarding remains prohibited.

The target must be a non-bare Git checkout inside the canonical home. The entire home
and escaping symlinks are rejected. Worktrees are supported when their common Git metadata
is within that home. Discovery and mount descriptors verify directory identities: changing
a connection or replacing a checkout cannot silently retarget an old workspace.

## Prepared external Console

In the agent’s **Console** connection, select an external target and click **Deploy code editor**
directly, then save the connection. SSH verification is automatic; no prior manual test is required.
The tooltip explains what deployment installs. Globally imposed configuration produces an explicit
reason when clicked. This administration action uploads
the versioned bundle over SFTP using the approved host key, builds and starts code-server,
verifies the service through its SSH tunnel and stores encrypted access in Galaris. No token
is returned to the browser.

**Test** and **Deploy code editor** preserve the connection’s saved activation state.
A new connection stays inactive until saved; these actions do not reactivate an
intentionally disabled connection. `repository_show` requires an active Console:
check this state if access is denied.

The Linux target needs Python 3, Docker with Compose accessible to the SSH account, user
namespaces and local SSH forwarding. The button does not install Docker or modify sshd.
Missing prerequisites produce an explicit failure; retry after correcting them. The initial
build can take several minutes and needs access to the pinned image and its package sources.

Each Unix account receives a private service with a Docker-assigned loopback port and retained
profiles. Only its home is mounted in the broker; IDE processes retain their approved repository
mounts. After initial installation, the deployment button disappears. Every `make update`,
in development, production and prepared releases, checks editors on active external SSH
connections that already have editor access configured. It compares the packaged bundle
with the installed bundle: a current service is verified without rebuilding or interrupting
sessions; a changed bundle is upgraded automatically. Inactive connections and those without
configured editors are not equipped automatically. A manually administered broker remains
your responsibility and is reported without modification.

Save files and end editor sessions before an upgrade; hidden sessions remain open. A live
session blocks replacement, and SSH, Docker or verification failures fail the overall update
instead of reporting incomplete success. Other independent targets are still checked. Correct
the problem and rerun `make update`.
The diagnostic identifies the stage (`inspection` or `upgrade`) and a recognized reason such as
`sessions_active`, `docker_access` or `user_namespaces`, without exposing remote output or secrets.
`unknown` means the controller supplied no recognized reason. This step runs after Galaris has
restarted and become ready: its failure does not mean the application has stopped. For
`sessions_active`, end sessions on all connections using the same Unix account, including hidden
sessions.
Upgrades preserve the private port, credential and retained
profiles, and restore the previous image if building or local verification fails. Session creation
waits during replacement. Automation never changes the configured access parameters.
A live IDE session also
prevents changing its runtime access; save its buffers and end it before that change. Previously presented
repositories retain their URI when their verified identity is unchanged; a replaced checkout
remains denied.

`repository_show` never installs remote software. For a manually administered deployment,
distribute the versioned `code-executor/` directory to the Linux target and use
[`compose.external.yaml`](../../../code-executor/compose.external.yaml):

1. Set `CODE_TARGET_HOME_ROOT` to the parent of approved Unix homes and retain their absolute
   paths in mounts. Do not mount `/` or a Docker socket in the runtime.
2. Once preparation is authorized, explicitly run
   `docker compose -f compose.external.yaml up -d --build` there. Port 8766 is loopback-only.
3. Transfer the control credential to the Galaris administrator over a private channel.
   Set Console parameters `code_runtime_port=8766` and `code_runtime_token`; the token is
   encrypted like other connection passwords.
4. Pin the Console SSH host key. Configure this transport identity with
   `AllowTcpForwarding local` and `PermitOpen 127.0.0.1:8766` under administered OpenSSH
   configuration. Other forwarding destinations remain prohibited.
5. Verify opening from Chat. Refused forwarding, a changed host key or an absent runtime
   produce an error, with no fallback copy or automatic installation.

Working SSH access to a repository alone does not provide its editor. If the runtime port
or token is missing from the Console connection, Chat reports that this external Console
is not configured for the editor. Check both parameters after preparation. Changing the
Console configuration manually changes the target identity: ask the agent to present the repository
again with `repository_show` before opening it.

The Console transport key and forge SSH keys have different purposes. Human Git uses
the latter inside the runtime, with the repository/home’s existing configuration.
Paths outside the home, unmounted SSH agents, specialized credential helpers and tools
missing from the runtime require administrator preparation. The complete Console terminal
environment and its service restarts are not provided.

## Operations, recovery and verification

The backend reconciles sessions every ten seconds. Streams recheck grants and connection
configuration at the same interval. IDE profiles survive expiry and revocation for authorized
recovery; retaining a profile grants no access. The pane provides no session deletion
control; obsolete profiles require administrator maintenance after drafts are saved.
Quotas reject new instances rather than evicting potentially
dirty buffers. The broker accepts at most eight active IDEs and 64 retained profiles,
with at most eight active IDEs per Unix account; stopped profiles do not consume that
active quota. The synthetic fixture used about 510 MiB
with one IDE; these limits suit the default 8 GiB memory ceiling. Extensions and larger
repositories can increase consumption: monitor that ceiling.
Runtime diagnostic logs are bounded to 1 MiB per session. Profiles can
contain work data: size and monitor the `code_profiles` volume.

A profile belongs to a human session: repository (Console connection and checkout),
Galaris user, read/edit mode and browser login family. Reopening reuses the matching live
session or a stopped profile for the same user/repository/mode. Other live login families
remain independent. The internal path is `/var/lib/galaris-code/sessions/<uuid>/profile/`,
in the embedded Console's `code_profiles` volume or the external runtime's `profiles` volume.

After expiry, **Retry** rechecks grants, login family and repository identity, resumes
the same profile if necessary and renews the cookie without replacing the iframe.
If the IDE process stopped, the pane retains this window and opens a recovery window
on the same profile. The native client cannot restore its old IPC connections after
a complete server restart. Users can access and copy drafts from the previous window.
Another restart requires confirmation before replacing only the recovery window;
the original stays retained and there are at most two iframes per open repository.
Network failures preserve the buffer; revoked access stays denied.

### Archive and recover a profile

Run maintenance only during an authorized administrator intervention. Save files and close
the Galaris tabs using the editor before stopping its runtime. The tool refuses concurrent
maintenance while the broker runs, and refuses profiles still mounted by orphaned IDE
processes. It never modifies repositories.

For the embedded Console, create a private backup directory, then:

```bash
mkdir -p artifacts/ide-backups
chmod 700 artifacts/ide-backups
docker compose stop code-executor
docker compose run --rm --no-deps --entrypoint python3 \
  -v "$PWD/artifacts/ide-backups:/backup" code-executor \
  /opt/galaris-code/profiles.py list
```

The tool makes no network requests. Reuse the `run` command, replacing `list` with:

- `archive <uuid> --output /backup/<uuid>.tar.gz` to back up a profile without removing it.
- `retire <uuid> --output /backup/<uuid>.tar.gz` to create a complete private archive before
  removing the profile from the quota. Backup errors or an existing archive leave the
  profile intact. Drafts are never automatically discarded.
- `restore /backup/<uuid>.tar.gz` to restore the same UUID without overwriting an existing profile.

Keep private archives on backed-up storage. Then run `docker compose start code-executor`
and reopen the repository as the authorized user. For an external Console, use its deployed
Compose file and the `runtime` service instead, retaining the same `profiles` volume.
Restoring a profile grants no access and cannot redirect it to a different checkout.

`make tests-code` checks mounts, consultation, worktrees and Git against a synthetic SSH
forge. Backend Code tests use `make tests` and ephemeral PostgreSQL. Pane tests use real
components with explicit fixtures; native scenarios in `compose.code-tests.yaml` use actual
code-server. They do not deploy or modify an existing installation.

The browser qualification exercises actual source saving through the gateway in Chromium,
Firefox and WebKit. Native Markdown webviews are qualified separately where working.
With this pinned upstream version, Firefox preview resource loads failed through its
virtual CDN; this limitation is accepted for the first stable delivery. Use Chromium
or WebKit for this preview; Firefox source editing remains supported. A separate
expected-failure scenario tracks the limitation without masking editing or recovery
regressions. A related upstream issue is
[code-server #7913](https://github.com/coder/code-server/issues/7913).
The image also lacks optional VSDA browser assets; native editing uses its fallback.

Galaris and its navigation extension retain CeCILL 2.1. Upstream code-server, VS Code OSS
MIT notices and third-party notices remain in the image; the extension includes the Galaris
license. No Microsoft Marketplace is added; code-server retains its upstream catalog.
Review licenses of any additional redistributed extensions.
