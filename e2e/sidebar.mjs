import { errors } from '@playwright/test'

// Dismiss an optional navigation drawer only while acting on the underlying page.
// Remove the handler before subsequent dialogs can cover the drawer's backdrop.
export async function withSidebarDismissal(page, action) {
  const backdrop = page.locator('body:not(:has([role="dialog"]:visible)) .q-drawer__backdrop')
  const width = page.viewportSize()?.width ?? await page.evaluate(() => window.innerWidth)
  await page.addLocatorHandler(backdrop, async element => {
    try {
      await element.click({ position: { x: width - 8, y: 150 }, timeout: 1000 })
    } catch (error) {
      // Route changes can close the drawer between handler activation and click.
      if (!(error instanceof errors.TimeoutError) || await element.isVisible()) throw error
    }
  })
  try {
    return await action()
  } finally {
    await page.removeLocatorHandler(backdrop)
  }
}
