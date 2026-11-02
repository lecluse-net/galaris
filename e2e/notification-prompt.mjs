// Optional onboarding is underneath dialogs and menus. Its handler must never
// steal focus from a popup or wait for an obscured button while that popup runs.
export function notificationPrompt(page) {
  return page.locator('body:not(:has(.q-menu:visible, [role="dialog"]:visible, [role="listbox"]:visible, [role="menu"]:visible)) .chat-notification-prompt')
}
