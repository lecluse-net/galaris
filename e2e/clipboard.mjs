// Replace only the OS clipboard boundary where browser permissions are absent.
export async function prepareClipboard(context, browserName) {
  if (browserName === 'chromium') {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    return
  }
  let text = ''
  await context.exposeBinding('__fixtureClipboardWrite', (_source, value) => { text = value })
  await context.exposeBinding('__fixtureClipboardRead', () => text)
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { value: {
      writeText: value => window.__fixtureClipboardWrite(value),
      readText: () => window.__fixtureClipboardRead(),
    } })
  })
}
