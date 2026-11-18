<p align="right"><a href="../../fr/user/desktop.md">Français</a> · <strong>English</strong></p>

# Install Galaris on Windows or Linux

[Back to the user guide](README.md)

The desktop client opens your Galaris server in a dedicated window. A server and network
connection are still required; the installer does not install the server.
The PWA and browser access remain available.

## Install and connect

When an [official release](https://github.com/lecluse-net/galaris/releases)
includes desktop files, choose the file for your x64 system:

- **Windows:** run `Galaris-<version>-x64.exe`, then open Galaris from the Start menu.
- **Linux, recommended:** place `Galaris-<version>-x86_64.AppImage` in a writable personal
  directory, enable execution in the file properties, and open it.
  Depending on your distribution, AppImage FUSE support may be needed.
- **Debian/Ubuntu:** `Galaris-<version>-amd64.deb` is an alternative integrated with the system.

On first launch, enter the **HTTPS** Galaris address supplied by your administrator,
such as `https://galaris.example.org`, then choose **Connect**. Use the base address,
without a path or query parameters. HTTPS certificates must be trusted by the system.
Then sign in through the usual Galaris interface.

The client restores the server on its next launch and retains its own session, separate from
your browser session. Galaris session expiration and revocation rules still apply.
Each server address has separate cookies and local data. To change servers or retry after
a network failure, use **Galaris → Change server…**. Closing this configuration window
returns to the existing Galaris window.

## Tabs and spelling

To the left of the tabs, **Back** and **Forward** browse the active tab’s page history.
They are disabled when no page is available in that direction. The **Reload** button
or **Ctrl+R** reloads the active tab. The **☰** button opens
the application menus (server selection, updates, editing, tabs and view); the classic
menu bar is hidden. **Alt+Left** and **Alt+Right** remain available.
In a wide window, this compact bar sits to the right of the sidebar, above the page
title, and follows the sidebar when it collapses. Only the active tab joins the page;
other tabs remain separated from its edge. In a narrow window, or on an external page,
the bar spans the window above the content.
Fullscreen previews and dialogs hide the bar until they close.

The **+** button after the last tab or **Ctrl+T** opens another Galaris page. **Ctrl+W** closes the current
tab; **Ctrl+Tab** and **Ctrl+Shift+Tab** switch tabs. Internal links opened with Ctrl+click,
the middle button or “Open link in new tab” stay in the window. Each page retains its
navigation and drafts when switching tabs. Tabs share the server session; restarting
reopens only its home page. Closing the last tab closes the window.
Each tab shows the title of its current page and follows page and language
changes. This information comes from the Galaris server interface: the server must also
be updated to replace the previous uniform “Galaris” title.

French/English spellchecking is enabled in text fields that allow it. Right-click an
underlined word for suggestions and **Add to dictionary**. Rich-text fields outside
Documents retain their custom menu: use **Shift+right-click** for native suggestions.
Code editors may disable
spellchecking. The first dictionary download requires Internet access; typed text is
not sent to the dictionary download service.

## Updates

The interface and web features come from the server, like the PWA. A server update does not
require reinstalling the client. Reloading may be necessary.

The **Windows** client and **Linux AppImage** check official releases for their own updates
at startup and every six hours. Downloads happen in the background. Once ready, choose
**Restart to update**, after saving your current work, or **Later**. Simply closing the
client does not trigger installation. **Galaris → Check for updates** allows manual checks
and retries. A failed download does not prevent using Galaris.
The AppImage must remain writable by its user.

If an editor reports unsaved changes, closing, switching servers or restarting is
cancelled. Return to the open window, save, then try again.

The **Debian** package does not replace itself automatically: download the new official
`.deb` and install it over the old version. Choose AppImage for integrated updates.
Development builds do not check for updates.

## Permissions and limitations

The client asks for permission before allowing the selected server to use the microphone,
camera, notifications, or clipboard reading. Operating system permissions still apply.
External links opened in a new window use your usual browser; resource previews stay
isolated inside the client. OAuth sign-in flows keep HTTPS navigation in the same window.

Closing the main window quits the client: this version does not run in the system tray
and does not guarantee notifications when closed. Calls and notifications require
qualification on your system; automated tests do not verify physical devices or Web Push
delivery.

Conversations, Tasks and Documents remain on the server. Uninstallation does not guarantee
logout: on a shared or transferred device, sign out in Galaris before uninstalling.
Changing servers retains the previous server's local session for a later return.

If connection fails, check the address, network and certificate validity. Do not disable
HTTPS protections. Never send passwords or cookies to support.
