<p align="right"><a href="../../fr/user/services.md">Français</a> · <strong>English</strong></p>

# Add and share services

A **Service** represents a provider, such as Nextcloud or GitLab, or a built-in Galaris
facility. Its protocols provide files, messaging or API access. A **Connection** links
an agent to that service with its settings and credentials. MCP tools remain individual
operations that an agent can call.

Open **Services & connections → Services → Catalog**, find a provider and choose
**Configure a copy**. The standard editor opens: review the name, enter your instance
addresses, select the useful protocols and save. Then create agent connections and set
their permissions. Adding a preset neither grants access nor activates agent connections.

The initial catalog includes Qonto, Nextcloud, GitLab, Matrix, n8n, Redmine and Telegram.
Each preset explains the capabilities it provides. REST access does not promise every
product feature; provider permissions and limitations still apply. For self-hosted APIs,
the standard `url` parameter holds the full API root. For Nextcloud and Matrix, complete
the protocol addresses before saving.

**Refresh from GitHub** retrieves available presets from `main` in the official repository.
The bundled catalog works offline. A failed refresh leaves the last usable catalog
available. Presets requiring a newer application or an unavailable protocol cannot be
used to create services.

Catalog refreshes never replace installed services. A different preset version is
indicated; **Configure a copy** lets you compare it under another name. Settings, secrets
and permissions on the first copy remain intact.

**New service** remains available for custom configurations. Add an SVG, PNG or GIF icon
in its form; YAML export includes the image without a separate file or remote link.
Share that single YAML file and import it on another installation. Connection secrets
are not exported. Icons are limited to 128 KiB; PNG/GIF to 1024 pixels per side and 100
animation frames. Active SVG content and external resources are rejected.

To contribute a preset, read the [catalog contract](../dev/service-catalog.md).
To delegate configuration, read [service administration](../admin/service-administration.md).
