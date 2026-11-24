<p align="right"><a href="../../fr/user/services.md">Français</a> · <strong>English</strong></p>

# Add and share services

A **Service** represents a provider, such as Nextcloud or GitLab, or a built-in Galaris
facility. Its protocols provide files, messaging or API access. A **Connection** links
an agent to that service with its settings and credentials. MCP tools remain individual
operations that an agent can call.

Open **Services & connections → Services** to see cards with the icon, a description excerpt,
capabilities and the number of existing connections, including inactive connections.
Card actions provide export, parameters, editing and deletion according to your privileges.
Built-in services reuse the menu icons in blue wherever possible and cannot be exported.
Services without a custom icon use the Services menu icon by default.
Click the name or description to open the full description.

The same icon accompanies the service in connection lists, filters and selectors,
including when creating a connection or setting permissions.

Every agent has **Contact** and **Tasks** connections. In **Authorizations**, select the Service
that owns the tool you want to configure. **Multimedia** includes audio, image and video tools.
**Browser** also includes `search_web`. Find team tools in **Agent**, `document_*` in
**Documents**, and `conversation_process_*` in **Processes**. **Chat** groups the internal
channel, calls and pending choices. See the [built-in Services guide](../admin/service-administration.md)
for permissions and scopes. Conversation tools retain their
original execution context.

Contact tools access the agent's own address book by default. A global manager can extend
the scope to agents in its teams or to all agents in **Permissions → Contact**. Each tool has
its own permission. Use Contact functions to read or edit a delegated address book.

The **Documents** and **Tasks** connections also have their own scopes. Documents tools
require the document's permissions as well as the connection scope.
In **Permissions → Tasks**, select **Team** to let the agent delegate work to teammates.

Click **New service** to open the catalog dialog, find a provider and choose
**Configure a copy**. The standard editor opens: review the name, enter your instance
addresses, select the useful protocols and save. Then create agent connections and set
their permissions. Adding a preset neither grants access nor activates agent connections.

For an HTTP or SSE MCP Service, choose the authentication type in its Service settings.
Selecting **OAuth 2.0** adds **Connect account** to the agent’s connection.
If you later change methods, the confirmation explains which credentials will be cleared.
Follow the [OAuth authorization steps](../admin/service-administration.md#mcp-oauth).

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

In the same dialog, **Create a custom service** opens an empty configuration. Add an SVG, PNG or GIF icon
in its form; YAML export includes the image without a separate file or remote link.
Share that single YAML file and import it on another installation. Connection secrets
are not exported. Icons are limited to 128 KiB; PNG/GIF to 1024 pixels per side and 100
animation frames. Active SVG content and external resources are rejected.

To contribute a preset, read the [catalog contract](../dev/service-catalog.md).
To delegate configuration, read [service administration](../admin/service-administration.md).
