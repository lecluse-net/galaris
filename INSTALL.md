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
make start
```

The first start builds the current sources, initializes the database and requires complete
schema convergence. Any Git branch or tag can be installed, independently of `APP_ENV`.
Qualified immutable bundles are also supported; follow
[image qualification](docs/en/dev/reliability-operations.md) to prepare one.

1. Open <http://localhost:8484> (or your configured address).
2. Click **Log in** and create the first administrator account.
3. In **Providers**, select **OpenRouter**, enter your API token and save.
4. Open **Chat**, select **Galaris** and send a message.

**The agent, models and default profile are preconfigured.** Only your OpenRouter token
is needed after account creation.

## UPDATE

Build and deploy the current checkout, on any branch or detached tag:

```bash
make update
```

List available tags and branches, then deploy your chosen reference:

```bash
make update VERSIONS
make update VERSION=<reference>
```

`APP_ENV` selects application behavior and Compose configuration; it never restricts Git
branches or source deployment. After configuration changes, run `make update`.
To deploy a qualified bundle without rebuilding, use `make update RELEASE_DIR=<directory>`.

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
