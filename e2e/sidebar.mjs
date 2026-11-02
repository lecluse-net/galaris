// Dismiss an optional navigation drawer only while acting on the underlying page.
// Remove the handler before subsequent dialogs can cover the drawer's backdrop.
export async function withSidebarDismissal(page, action) {
  const backdrop = page.locator('body:not(:has([role="dialog"]:visible)) .q-drawer__backdrop')
  await page.addLocatorHandler(backdrop, async element => {
    const width = await page.evaluate(() => window.innerWidth)
    await element.click({ position: { x: width - 8, y: 150 } })
  })
  try {
    return await action()
  } finally {
    await page.removeLocatorHandler(backdrop)
  }
}
