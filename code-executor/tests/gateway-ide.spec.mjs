import { test, expect } from '@playwright/test'

test.afterEach(async ({ page, request }) => {
  const frame = page.frames().find(value => value.url().includes('/gateway/') && value.url().includes('/editor/'))
  if (frame) {
    const session = new URL(frame.url()).pathname.split('/gateway/')[1].split('/')[0]
    expect((await request.post(`http://localhost:8484/api/code/qualification/${session}/close`)).ok()).toBeTruthy()
  }
})

for (const stopped of [false, true]) {
test(`real IDE loads and edits through the Galaris gateway (runtime stopped: ${stopped})`, async ({ page, request }) => {
  const failures = []
  const sockets = []
  page.on('websocket', socket => sockets.push(socket.url()))
  page.on('requestfailed', value => failures.push(value.url()))
  await request.post('http://fixture:8766/test/write', { data: { text: 'synthetic initial gateway diff\n' } })
  await page.goto('http://localhost:8484/api/code/qualification/parent')
  await page.getByRole('button', { name: 'Open synthetic repository' }).click()
  const ide = page.frameLocator('iframe[title="Synthetic IDE"]')
  await expect(ide.locator('.monaco-workbench')).toBeVisible()
  await expect(page.locator('#ready')).toHaveText('galaris.code.ready')
  const cookies = await page.context().cookies()
  expect(cookies.find(value => value.name === 'galaris_code')).toMatchObject({ httpOnly: true, sameSite: 'Strict' })
  const editorUrl = new URL(page.frames().find(frame => frame.url().includes('/editor/')).url())
  expect(editorUrl.origin).toBe(new URL(page.url()).origin)
  expect(editorUrl.href).not.toContain('ticket=')
  const trust = ide.getByRole('button', { name: 'Trust', exact: true })
  await expect(trust).toBeVisible()
  await trust.click()
  // Git may already have dismissed the trust editor after trust was granted.
  await page.keyboard.press('Escape')
  await expect(ide.getByRole('tab', { name: /Git: Changes/ })).toHaveAttribute('aria-selected', 'true')
  await ide.getByRole('tab', { name: /^Explorer/ }).click()
  await ide.getByRole('treeitem', { name: 'source.txt', exact: true }).dblclick()
  // Chromium uses native EditContext; Firefox/WebKit expose Monaco's textarea.
  const input = ide.getByRole('textbox', { name: /^source\.txt(?:,|$)/ })
  // Chromium's native EditContext focus target has no visible box of its own.
  await expect(input).toBeAttached()
  const saved = `synthetic human gateway save ${test.info().project.name}`
  const modifier = await input.evaluate(() => /Mac/.test(navigator.platform + navigator.userAgent) ? 'Meta' : 'Control')
  await input.focus()
  await page.keyboard.press(`${modifier}+a`)
  await page.keyboard.type(saved)
  await page.keyboard.press(`${modifier}+s`)
  await expect.poll(async () => (await (await request.get('http://fixture:8766/test/status')).json()).text).toBe(saved)
  // Expiry recovery uses the same frame and process, retaining its unsaved text.
  const unsaved = `synthetic retained recovery draft ${test.info().project.name}`
  await input.focus()
  await page.keyboard.press(`${modifier}+a`)
  await input.pressSequentially(unsaved, { delay: 20 })
  const retainedEditor = ide.locator('.monaco-editor').filter({ has: input }).locator('.view-lines')
  await expect(retainedEditor).toContainText(unsaved)
  const session = editorUrl.pathname.split('/gateway/')[1].split('/')[0]
  const previousSockets = sockets.length
  expect((await request.post(`http://localhost:8484/api/code/qualification/${session}/expire?stop=${stopped}`)).ok()).toBeTruthy()
  const response = await page.request.post(`http://localhost:8484/api/code/qualification/${session}/resume`)
  expect(response.ok()).toBeTruthy()
  const recovery = await response.json()
  expect(recovery.restart_required).toBe(stopped)
  expect((await page.context().cookies()).find(value => value.name === 'galaris_code').value).not.toBe(cookies.find(value => value.name === 'galaris_code').value)
  let writable = input
  if (stopped) {
    // The shared pane retains its original iframe and opens a recovery window.
    // Reproduce that DOM behavior with the real IDE, without discarding its draft.
    await page.evaluate(url => {
      const frame = document.createElement('iframe')
      frame.id = 'recovered'
      frame.src = url
      frame.style = 'width:95vw;height:85vh;border:0'
      document.body.appendChild(frame)
    }, recovery.url)
    const fresh = page.frameLocator('#recovered')
    await expect(fresh.locator('.monaco-workbench')).toBeVisible()
    const explorer = fresh.getByRole('tab', { name: /^Explorer/ })
    // A recovered profile may already have its Explorer open; clicking its
    // selected activity tab would collapse the sidebar instead of opening it.
    if (await explorer.getAttribute('aria-expanded') !== 'true') await explorer.click()
    const file = fresh.getByRole('treeitem', { name: 'source.txt', exact: true })
    await expect(file).toBeVisible()
    await file.dblclick()
    writable = fresh.getByRole('textbox', { name: /^source\.txt(?:,|$)/ })
    await expect(writable).toBeAttached()
    await writable.focus()
    await page.keyboard.press(`${modifier}+a`)
    await writable.pressSequentially(unsaved, { delay: 20 })
  }
  // Revocation watches close old-cookie streams within ten seconds. The native
  // client must reconnect using the renewed cookie without reloading its buffer.
  await expect.poll(() => sockets.length, { timeout: 30_000 }).toBeGreaterThan(previousSockets)
  await expect(retainedEditor).toContainText(unsaved)
  await writable.focus()
  await page.keyboard.press(`${modifier}+s`)
  await expect.poll(async () => (await (await request.get('http://fixture:8766/test/status')).json()).text).toBe(unsaved)
  // This pinned upstream image lacks the optional VSDA browser assets. Its native
  // fallback works; retain the observation separately from gateway failures.
  const upstreamWarnings = failures.filter(url => /\/node_modules\/vsda\/rust\/web\/vsda\.js$/.test(url))
  await test.info().attach('upstream-asset-observation', { body: JSON.stringify(upstreamWarnings), contentType: 'application/json' })
  expect(failures.filter(url => url.includes('/api/code/gateway/') && !upstreamWarnings.includes(url))).toEqual([])
})
}

test('native Markdown preview support is qualified independently of source editing', async ({ page, browserName }) => {
  await page.goto('http://localhost:8484/api/code/qualification/parent')
  await page.getByRole('button', { name: 'Open synthetic repository' }).click()
  const ide = page.frameLocator('iframe[title="Synthetic IDE"]')
  await expect(ide.locator('.monaco-workbench')).toBeVisible()
  const trust = ide.getByRole('button', { name: 'Trust', exact: true })
  await expect(trust).toBeVisible()
  await trust.click()
  await page.keyboard.press('Escape')
  await expect(ide.getByRole('tab', { name: /Git: Changes/ })).toHaveAttribute('aria-selected', 'true')
  await ide.getByRole('tab', { name: /^Explorer/ }).click()
  await ide.getByRole('treeitem', { name: /README\.md/ }).dblclick()
  const input = ide.getByRole('textbox', { name: /^README\.md(?:,|$)/ })
  await expect(input).toBeAttached()
  const modifier = await input.evaluate(() => /Mac/.test(navigator.platform + navigator.userAgent) ? 'Meta' : 'Control')
  await input.focus()
  await page.keyboard.press(`${modifier}+Shift+v`)
  await expect(ide.locator('iframe.webview')).toBeVisible()
  // A separate expected failure keeps the accepted Firefox limitation visible
  // without allowing it to mask a regression in saving or session recovery.
  test.fail(browserName === 'firefox', 'Pinned upstream Markdown webview virtual CDN resources fail in Firefox; source editing is supported.')
  await expect(ide.frameLocator('iframe.webview').frameLocator('#active-frame').getByText('Synthetic Markdown webview content.', { exact: true })).toBeVisible()
})
