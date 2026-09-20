import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document } from './data.mjs'

const js = '  const greeting = "Bonjour ☀";\n  console.log(greeting, 42);\n'
const html = `<h2>Exemples de code</h2><pre><code class="language-javascript">${js}</code></pre><pre><code class="language-python">def hello(name):\n    return "Bonjour " + name\n</code></pre><p>Texte normal et <code>code en ligne</code>.</p>`
const saved = page => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)

for (const dark of [false, true]) {
  test(`document code is highlighted while editing and reading in ${dark ? 'dark' : 'light'} mode`, async ({ page }, testInfo) => {
    await mount(page, 'core/util/components/RichTextEditor.vue', { dark, props: { profile: 'document', modelValue: html } })
    const editor = page.locator('.ck-editor__editable')
    const code = editor.locator('pre code').first()
    await expect(code.locator('.hljs-keyword').first()).toHaveText('const')
    await expect(code).toHaveCSS('font-family', /monospace/)
    await expect(editor.locator('pre code').nth(1).locator('.hljs-keyword').first()).toHaveText('def')
    expect(await saved(page)).toBeUndefined()
    await page.screenshot({ path: testInfo.outputPath(`document-code-${dark ? 'dark' : 'light'}.png`) })

    // Replace a selected keyword, then restore it through the native undo stack.
    await code.locator('.hljs-keyword').first().dblclick()
    await expect.poll(() => page.evaluate(() => window.getSelection()?.toString())).toBe('const')
    await page.keyboard.insertText('cost')
    await expect.poll(() => saved(page)).toContain('cost greeting')
    await expect(code.locator('.hljs-keyword')).toHaveCount(0)
    await page.keyboard.press('Control+z')
    await expect(code.locator('.hljs-keyword').first()).toHaveText('const')
    expect(await saved(page)).toContain(js)
    expect(await saved(page)).not.toMatch(/hljs-|codeSyntax/)

    // Source mode remains available, and changing documents removes obsolete markers.
    await page.getByRole('button', { name: 'Source', exact: true }).click()
    await expect(page.locator('.galaris-source-highlight')).toBeVisible()
    await expect(page.locator('.ck-source-editing-area textarea')).not.toHaveValue(/hljs-|codeSyntax/)
    await page.getByRole('button', { name: 'Source', exact: true }).click()
    await expect(code.locator('.hljs-keyword').first()).toHaveText('const')
    await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Another document</p>' }))
    await expect(editor.locator('pre')).toHaveCount(0)
    await page.evaluate(value => window.testApp.setProps({ modelValue: value, readonly: true }), html)
    await expect(editor).toHaveAttribute('contenteditable', 'false')
    await expect(code.locator('.hljs-keyword').first()).toHaveText('const')

    await page.evaluate(({ html, dark }) => window.testApp.mount({ component: 'core/util/components/RichText.vue', dark, props: { profile: 'document', content: html } }), { html, dark })
    const reading = page.locator('.rich-content pre code').first()
    expect(await reading.textContent()).toBe(js)
    const keyword = reading.locator('.hljs-keyword').first()
    await expect(keyword).toHaveText('const')
    const initialColor = await keyword.evaluate(node => getComputedStyle(node).color)
    expect(initialColor).not.toBe(await reading.evaluate(node => getComputedStyle(node).color))
    await page.evaluate(dark => window.testApp.dark(!dark), dark)
    await expect.poll(() => keyword.evaluate(node => getComputedStyle(node).color)).not.toBe(initialColor)
    expect(await reading.textContent()).toBe(js)
  })
}

test('unlabelled code is detected, literal HTML stays inert and unsupported languages stay readable', async ({ page }) => {
  const content = '<pre><code>const answer = "hello";\nconsole.log(answer);</code></pre><pre><code class="language-html">  &lt;script&gt;window.codeExecuted = true;&lt;/script&gt;\n</code></pre><pre><code class="language-unknown">  untouched &lt;text&gt;\n</code></pre>'
  await mount(page, 'core/util/components/RichText.vue', { props: { profile: 'document', content } })
  const blocks = page.locator('.rich-content pre code')
  await expect(blocks.first().locator('.hljs-keyword').first()).toHaveText('const')
  expect(await blocks.nth(1).textContent()).toBe('  <script>window.codeExecuted = true;</script>\n')
  await expect(blocks.nth(1).locator('script')).toHaveCount(0)
  expect(await page.evaluate(() => window.codeExecuted)).toBeUndefined()
  expect(await blocks.nth(2).textContent()).toBe('  untouched <text>\n')
  await expect(blocks.nth(2)).toBeVisible()
})

test('code keeps its highlighting in static reading and on the printed page', async ({ page }) => {
  await page.addInitScript(() => { window.print = () => { window.printCalls = 1 } })
  await mount(page, 'core/util/components/RichText.vue', { dark: true, props: { profile: 'document', content: html + '<script>document.body.dataset.loaded = "yes"</script>' } })
  const interactive = page.locator('.rich-content')
  await expect(page.locator('.rich-content script,iframe')).toHaveCount(0)
  expect(await page.locator('body').getAttribute('data-loaded')).toBeNull()
  expect(await interactive.locator('pre code').first().textContent()).toBe(js)
  await expect(interactive.locator('.hljs-keyword').first()).toHaveText('const')
  await page.evaluate(html => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', dark: true, props: { profile: 'document', modelValue: html } }), html)
  await page.getByRole('button', { name: 'Print', exact: true }).click()
  const frame = page.frameLocator('.document-print-frame')
  await expect(frame.locator('.hljs-keyword').first()).toHaveText('const')
  expect(await frame.locator('pre code').first().textContent()).toBe(js)
})

test('the actual document screen shows code colors and autosaves only authored content', async ({ page }, testInfo) => {
  let current = { ...document, media_type: 'text/html', content_profile: 'document', content_profile_version: 1, payload: { text: html } }
  const updates = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/folders?*', [{ path: 'Reports', kind: 'custom', shared: false }])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments?*', [])
  await page.route('**/api/memory/items/doc-a?*', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: current })
    const body = route.request().postDataJSON()
    updates.push(body)
    current = { ...current, ...body, revision: current.revision + 1 }
    return route.fulfill({ json: current })
  })
  await mount(page, 'core/util/components/WorkingDocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7, editable: true }, privileges: ['MEMORY_EDIT'] })
  const code = page.locator('.ck-editor__editable pre code').first()
  await expect(code.locator('.hljs-keyword').first()).toHaveText('const')
  expect(updates).toEqual([])
  await code.locator('.hljs-number').click()
  await page.keyboard.press('End')
  await page.keyboard.insertText(' // saved')
  await expect.poll(() => updates.length).toBe(1)
  expect(updates[0].payload.text).toContain('// saved')
  expect(updates[0].payload.text).not.toMatch(/hljs-|codeSyntax/)
  await expect(code.locator('.hljs-comment')).toHaveText('// saved')
  await page.screenshot({ path: testInfo.outputPath('actual-document-code.png') })
})
