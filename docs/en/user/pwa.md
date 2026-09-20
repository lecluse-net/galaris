<p align="right"><a href="../../fr/user/pwa.md">Français</a> · <strong>English</strong></p>

# Install and use Galaris as a mobile app

[Back to the user guide](README.md)

Galaris is a Progressive Web App (PWA). A compatible browser can install it from the existing
site: no APK package, store account, or App Store visit is required.
Once installed, it has its own icon and opens in a standalone window.

## Before you begin

You need:

- the HTTPS address of Galaris provided by your administrator;
- an active Galaris account;
- Chrome on Android or Safari on iPhone;
- a network connection to use Galaris data and actions.

The PWA retains static interface elements, but it does not cache conversations,
tasks, or API responses. It therefore does not replace a network connection.

## Installation on Android

1. Open the Galaris address in **Chrome**.
2. Open the **⋮** menu in the upper-right corner.
3. Choose **Install app**. Depending on the Chrome version, the label may be
   **Add to Home screen**.
4. Confirm the installation.
5. Close the tab, launch Galaris from its new icon, and sign in for the first time.

Chrome may also display an installation prompt directly. If Galaris is already
installed, the option is no longer offered.

## Installation on iPhone

1. Open the Galaris address in **Safari**.
2. Tap the **Share** button — the square with an upward-pointing arrow.
3. Scroll through the actions and choose **Add to Home Screen**.
4. Keep the suggested name, then tap **Add**.
5. Launch Galaris from its new icon and sign in for the first time.

Use Safari for this installation: another iOS browser may not display the same
action or follow the same process.

## Persistent sign-in

After this first sign-in, Galaris automatically restores the session at launch. The
default duration is 30 days from the last use that renewed the session;
the administrator can choose a different duration.

The session ends when:

- you use **Sign out** in Galaris;
- you change your password;
- your account is disabled;
- the configured inactivity period is exceeded;
- the site data is cleared by the browser or system.

Uninstalling the icon does not guarantee that you are signed out. On a shared,
lost, or resold device, sign out first. If the device is no longer accessible, change your
password from another device to revoke persistent sessions.

## Updates

The PWA automatically searches for and installs new versions of its interface. An update
generally becomes visible after you completely close the application and then
reopen it. Conversations and tasks are stored on the server side and do not depend on
reinstalling the icon.

Clear the site data only as a last resort: this action deletes the local session and
requires you to sign in again.

## Troubleshooting

| Problem | Checks |
|---|---|
| the installation option is missing | open the HTTPS URL in Chrome or Safari, exit private browsing, reload the page, and check that the application is not already installed |
| the icon opens a regular tab | delete only the old icon, then reinstall from the compatible browser |
| Galaris asks for the password at every launch | open the application from its icon, allow cookies, and check that the browser does not automatically delete site data |
| the interface appears outdated | completely close the PWA and then reopen it; wait a few seconds with the network active |
| pages open but data does not load | check the network connection: APIs and business data are not available offline |

If the problem persists, provide the administrator with the address used, the phone model,
the system version, and the browser. Never provide your password or the browser's cookies.
