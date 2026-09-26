# Galaris installation and operations

Requirements: Linux, Docker with Compose, Git, GNU Make, OpenSSL and `ss` (`iproute2`).
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

The first start builds images and initializes the database; allow a few minutes.

1. Open <http://localhost:8484> (or your configured address).
2. Click **Log in** and create the first administrator account.
3. In **Providers**, select **OpenRouter**, enter your API token and save.
4. Open **Chat**, select **Galaris** and send a message.

**The agent, models and default profile are preconfigured.** Only your OpenRouter token
is needed after account creation.

## UPDATE

Update the current branch:

```bash
git pull --ff-only
make update
```

Or list available tags and branches, then deploy your chosen reference:

```bash
make update VERSIONS
make update VERSION=<reference>
```

After configuration changes, run `make update` to apply them.

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
