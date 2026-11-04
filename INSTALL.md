# Galaris installation and operations

Requirements: Linux, Docker with Compose, Git, GNU Make, OpenSSL, `flock` (`util-linux`) and `ss` (`iproute2`).
Python, Node.js and PostgreSQL run in Docker. Run all commands from the `galaris` directory.

## INSTALL

```bash
git clone https://github.com/lecluse-net/galaris.git galaris
cd galaris
make install
```

> **Optional configuration — before starting:** edit `.env` and `compose.override.yaml`
> now if you need to customize the public URL, ports, database or other settings.
> Otherwise, keep the defaults: embedded PostgreSQL and port **8484**.

```bash
make update RELEASE_DIR=/path/to/qualified-release
```

Production installs and updates use qualified immutable images. Obtain a prepared bundle,
or follow [image qualification](docs/en/dev/reliability-operations.md) to build and test one.
Startup initializes the database and requires complete schema convergence.
Development builds from sources with `APP_ENV=dev make start`.

1. Open <http://localhost:8484> (or your configured address).
2. Click **Log in** and create the first administrator account.
3. In **Providers**, select **OpenRouter**, enter your API token and save.
4. Open **Chat**, select **Galaris** and send a message.

**The agent, models and default profile are preconfigured.** Only your OpenRouter token
is needed after account creation.

## UPDATE

Deploy the qualified bundle without rebuilding its images:

```bash
make update RELEASE_DIR=/path/to/qualified-release
```

In development, list available tags and branches, then deploy your chosen reference:

```bash
make update VERSIONS
APP_ENV=dev make update VERSION=<reference>
```

After production configuration changes, redeploy with the qualified bundle. Bare `make update`
is reserved for development source builds.

## BACKUP AND RESTORE

```bash
make save
make save FILE=/safe/location/galaris.tar.gz
make restore /safe/location/galaris.tar.gz
```

The archive includes a full PostgreSQL dump, configuration, recovery keys and `/data` except
`/data/files`. Save briefly stops application writers and resumes previously running services.
Restore validates the archive, saves the current state, stages a new database and replaces
database/data while leaving `/data/files` untouched. Services remain stopped after restoration.
Manage `/data/files` separately with rsync and use the matching snapshot before restarting.
Use `make save KEEP_STOPPED=1` to keep application writers stopped until that rsync finishes,
then resume with `make start`.
Archives contain secrets and must remain private. See the [backup contract](docs/en/admin/installation.md#backup-and-restore).

## UNINSTALL

Remove Galaris containers and networks, choosing which additional resources to delete:

```bash
make uninstall
```

To accept all cleanup options automatically:

```bash
make uninstall FORCE
```

**FORCE permanently deletes Compose-managed volumes and their data**, local Compose images
and orphan containers. Configuration files, host-mounted directories and external databases
or volumes are preserved.

## OPERATIONS

Stop services without deleting data, then start them again when needed:

```bash
make stop
make start
```

View service logs with `make logs`.

See the [detailed installation guide](docs/en/admin/installation.md) for advanced configuration.
