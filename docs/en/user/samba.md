<p align="right"><a href="../../fr/user/samba.md">Français</a> · <strong>English</strong></p>

# Access a Samba or Windows share

The **Samba / SMB 2–3** bridge exposes share files through **File sharing** functions.
The server must be reachable from the Galaris backend, usually on TCP port 445.
Galaris does not require a mounted drive.

1. In **Tools**, create a Tool with a code such as `team-share`, enable its file-sharing
   capability and select **Samba / SMB 2–3**.
2. In the **File sharing** tab, set **Share address (base_url)**.
   `smb://files.example.test` exposes the server’s shares: the agent lists
   `team-share://`, then browses `team-share://<share>/...` through generic file-sharing
   functions. To restrict the root, use `smb://files.example.test/shared` or
   `smb://files.example.test:445/shared/team`. The configured share and subdirectory
   must already exist. This URL contains no credentials.
   The **Technical name** remains an identifier such as `team-share`: it contains
   neither the SMB URL, nor `://`, nor underscores.
3. Declare connection parameters `login` (text) and `password` (password), then map
   them to the matching bridge parameters. The login can be `user` or `DOMAIN\user`.
4. To require SMB 3 encryption, declare a text parameter `encrypt`, map it to the
   bridge and set its connection value to `true`. Without this parameter, the bridge
   requires SMB signing and accepts SMB 2 or SMB 3.
5. Create and activate a connection for the agent and enter its credentials.
   Remote account permissions apply to every operation.

## Browse files with the agent

Ask the agent to list `team-share://`, then follow the returned URIs.
With a server root, this first listing contains accessible shares.
The agent opens, for example, `team-share://shared/`, then that share's folders
and files. It uses only generic `file_list`, `file_info`, `file_read` and
authorized **File sharing** mutations; the bridge adds no dedicated SMB functions
to its catalogue.

| Address configured by the administrator | Root seen by the agent | Example file |
|---|---|---|
| `smb://files.example.test` | Share listing | `team-share://shared/reports/result.txt` |
| `smb://files.example.test/shared` | Contents of `shared` | `team-share://reports/result.txt` |
| `smb://files.example.test/shared/team` | Contents of `shared/team` | `team-share://reports/result.txt` |

The scheme always matches the Tool code; paths are relative to the configured root.
Reuse the exact returned URIs, including spaces, accents and encoded characters.
Credentials are resolved on the server. Separate Tools can target different servers
or roots.

A Tool carrying only this file capability is not a Task-only function catalogue:
its resources use the `file_*` functions authorized in the current context.

## Permissions and limits

The agent receives neither the SMB address nor credentials: it uses only Tool URIs
and `file_*` functions. A server root uses SRVSVC over authenticated SMB and lists
only disk shares accessible to the account. Printers and IPC endpoints are not folders.
Server permissions remain enforced on every access. Servers without SRVSVC require
an explicit share root in the configuration. Shares themselves cannot be created or deleted.
Moving between shares copies the file, then deletes the source with a version
precondition; a denied deletion reports that only the copy succeeded.

The bridge supports name and small UTF-8 text searches, paginated listings,
bounded reads, file creation, replacement, append, editing, copy, move and deletion.
Indexing can be excluded, restricted to known URIs or recursive through the standard
connection parameter. Directories cannot be moved or deleted.

Reads expose an `etag`; edits and appends check the version under an SMB lock.
A conflict requires a fresh read. Replacement writes into the locked file: a network
interruption may leave partial content; inspect the file before retrying.
Mutations are never automatically replayed.

DFS shares and SMB reparse points are rejected. Configure the final server directly
and disable links escaping the share on Samba (`wide links = no`). SMB 1, guest access,
Kerberos and public sharing links are not provided. Listings allow 500 results per
page and 10,000 entries per directory; a larger directory requires a smaller root.

## Diagnose access

- A rejected **Technical name** means the code does not match the indicated format:
  enter `team-share`, then put the SMB address in `base_url`.
- A `base_url` configuration error must be corrected in the Tool; the agent keeps
  using its `team-share://` URIs.
- An authentication denial concerns the connection login or password.
  A missing share may also be forbidden for that account.
- If SRVSVC is unavailable, configure an existing share directly as the root.
  For a network error, check server resolution and TCP 445 from the backend.
- A round interruption or expired lease does not prove a Samba denial: inspect
  the `file_*` calls and results actually recorded. In development, a backend
  reload can interrupt the round.

The automated `make tests-samba` journey uses synthetic accounts, a real ephemeral
Samba server and isolated PostgreSQL. It covers share enumeration, fragmented
SRVSVC responses, pagination, permissions, version conflicts and transfers between
shares.
