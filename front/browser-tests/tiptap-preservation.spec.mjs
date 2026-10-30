import { test, expect, mount, editorHtml } from './fixtures.mjs'
const component = 'core/util/components/RichTextEditor.vue'
const lastValue = page => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)
const rich = '<h2>Reference document</h2><p><u>Underlined</u> <span style="font-family: Georgia; font-size: 24px; color: #087ff5">Styled</span></p><ol start="3" reversed><li><p>First</p><ul><li><p>Nested</p></li></ul></li></ol><figure class="table"><table><tbody><tr><th colspan="2" colwidth="120,180"><p>Header</p></th></tr><tr><td><p>Left</p></td><td><p>Right</p></td></tr></tbody></table><figcaption>Table caption</figcaption></figure><pre><code class="language-html" data-code-lines="true">  &lt;p&gt;\n    a  b\n</code></pre>'
const interactive = '<section class="custom-layout"><canvas id="scene" width="240" height="120"></canvas><button id="rotate">Rotate</button><p class="result">Ready</p></section><style>.custom-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 17px; } @media(max-width: 500px) { .custom-layout { grid-template-columns: 1fr; } }</style><script>const scene = new THREE.Scene(); const camera = new THREE.PerspectiveCamera(60, 2, 0.1, 100); camera.position.z = 3; const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById("scene") }); renderer.setSize(240,120); const mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial({color:0x087ff5})); scene.add(mesh); renderer.render(scene,camera); document.getElementById("rotate").onclick = () => { mesh.rotation.y += 1; renderer.render(scene,camera); document.querySelector(".result").textContent = "Rotated"; };</script>'

test('Tiptap preserves the editorial corpus through editing, serialization, reopening and reading', async ({ page }) => {
  await mount(page, component, { props: { modelValue: rich, profile: 'document', ariaLabel: 'Editorial content' } })
  const editor = page.getByRole('textbox', { name: 'Editorial content' })
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  await expect(editor.locator('ol')).toHaveAttribute('start', '3')
  await expect(editor.locator('ol')).toHaveAttribute('reversed', '')
  expect(await lastValue(page)).toBeUndefined()
  await editor.locator('h2').click(); await page.keyboard.press('End'); await page.keyboard.type('!')
  const saved = await lastValue(page)
  expect(saved).toContain('<u>Underlined</u>'); expect(saved).toContain('font-family: georgia'); expect(saved).toContain('Table caption'); expect(saved).toContain('data-code-lines="true"'); expect(saved).toContain('  &lt;p&gt;\n    a  b\n')
  expect(saved).not.toMatch(/hljs-|galaris-code-line|blob:|ProseMirror/)
  expect(await editorHtml(page)).toBe(saved)
  await page.evaluate(value => window.testApp.mount({ component: 'core/util/components/RichText.vue', props: { profile: 'document', content: value } }), saved)
  await expect(page.locator('figcaption')).toHaveText('Table caption')
})

test('editing surrounding text and reloading retain custom HTML CSS and JavaScript without execution in the editor', async ({ page }) => {
  await mount(page, component, { props: { modelValue: '<p>Before</p>' + interactive + '<p>After</p>', profile: 'document' } })
  const editor = page.locator('[data-editor-surface]')
  await expect(editor.locator('.embedded-code-widget')).toHaveCount(1)
  await expect(editor.locator('script,style,canvas')).toHaveCount(0)
  await editor.locator('p').first().click(); await page.keyboard.press('End'); await page.keyboard.type('!')
  const saved = await lastValue(page)
  expect(saved).toContain(interactive)
  await page.evaluate(modelValue => window.testApp.setProps({ modelValue }), saved.replace('gap: 17px', 'gap: 23px'))
  await editor.locator('p').first().click(); await page.keyboard.press('End'); await page.keyboard.type('?')
  expect(await lastValue(page)).toContain('gap: 23px')
  await page.evaluate(value => window.testApp.setProps({ modelValue: value }), '<p>Other document</p>')
  await page.evaluate(value => window.testApp.setProps({ modelValue: value }), saved)
  expect(await editorHtml(page)).toBe(saved)
})

test('independent opaque objects leave intervening prose and inherited-color tables editable', async ({ page }) => {
  const first = '<section><h2>First object</h2><svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"></circle></svg></section>'
  const second = '<section><h2>Second object</h2><details><summary>Details</summary>Content</details></section>'
  const table = '<table style="color: inherit"><tbody><tr><td>Editable cell</td></tr></tbody></table>'
  await mount(page, component, { props: { profile: 'document', modelValue: first + '<p>Between objects</p>' + table + second } })
  const editor = page.locator('[data-editor-surface]')
  await expect(editor.locator('.embedded-code-widget')).toHaveCount(2)
  await expect(editor.locator('td')).toBeEditable()
  await editor.locator('p').filter({ hasText: 'Between objects' }).click()
  await page.keyboard.press('End'); await page.keyboard.type('!')
  const saved = await lastValue(page)
  expect(saved).toContain(first)
  expect(saved).toContain('<p>Between objects!</p>')
  expect(saved).toContain(second)
  expect(saved).toContain('color: inherit')
  await page.evaluate(modelValue => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: { profile: 'document', modelValue } }), saved)
  await expect(editor.locator('.embedded-code-widget')).toHaveCount(2)
  await expect(editor.locator('td')).toHaveText('Editable cell')
})

test('shared style and script regions retain their common document and source order', async ({ page }) => {
  const source = '<section id="first">First</section><p>Shared prose</p><section id="second">Second</section><style>#first + p { font-weight: bold }</style><script>document.getElementById("second").textContent = document.getElementById("first").textContent;</script>'
  await mount(page, component, { props: { profile: 'document', modelValue: '<p>Before</p>' + source + '<p>After</p>' } })
  const editor = page.locator('[data-editor-surface]')
  await expect(editor.locator('.embedded-code-widget')).toHaveCount(1)
  await expect(editor.locator('p').filter({ hasText: 'Shared prose' })).toHaveCount(0)
  await editor.locator('p').first().click(); await page.keyboard.press('End'); await page.keyboard.type('!')
  expect(await lastValue(page)).toContain(source)
})

test('Three.js runs offline inside the real isolated document runtime with custom CSS and controls', async ({ page }) => {
  const external = []; page.on('request', req => { if (/^https?:/.test(req.url()) && !req.url().startsWith('http://localhost:8000')) external.push(req.url()) })
  await mount(page, 'core/util/components/RichText.vue', { props: { content: '' } })
  await page.evaluate(source => window.testApp.mount({ component: 'app/document/components/DocumentApplicationBlock.vue', props: { source, language: 'galaris-raw-html', documentId: 'synthetic-document', revision: 1, ready: true, registerSnapshot: capture => { window.threeCapture = capture } } }), interactive)
  const inner = page.frameLocator('iframe').frameLocator('iframe')
  await expect(inner.getByText('Ready', { exact: true })).toBeVisible()
  await expect(inner.locator('canvas')).toBeVisible()
  await inner.getByRole('button', { name: 'Rotate' }).click()
  await expect(inner.getByText('Rotated', { exact: true })).toBeVisible()
  const canvas = await inner.locator('canvas').evaluate(element => { const blank = document.createElement('canvas'); blank.width = element.width; blank.height = element.height; return { image: element.toDataURL(), blank: blank.toDataURL(), css: getComputedStyle(element.parentElement).display } })
  expect(canvas.image).toMatch(/^data:image\/png;base64,/); expect(canvas.image).not.toBe(canvas.blank); expect(canvas.css).toBe('grid'); expect(external).toEqual([])
  await expect.poll(() => page.evaluate(() => typeof window.threeCapture)).toBe('function')
  const snapshot = await page.evaluate(() => window.threeCapture(new AbortController().signal))
  expect(snapshot).toContain(canvas.image); expect(snapshot).toContain('Rotated'); expect(snapshot).not.toContain('<script')
})

test('canonical internal links retain identity through formatting and reopening', async ({ page }) => {
  const uri = 'galaris://goal/11111111-1111-4111-8111-111111111111'
  await mount(page, component, { props: { modelValue: `<p><a href="${uri}">My goal</a> remains here.</p>` } })
  const editor = page.locator('[data-editor-surface]'); await editor.locator('p').click(); await page.keyboard.press('End'); await page.keyboard.type('!')
  expect(await lastValue(page)).toContain(`href="${uri}"`)
  expect(await lastValue(page)).not.toContain('data-rich-reference')
})

test('table insertion, cell editing, undo and read-only retain content', async ({ page }) => {
  await mount(page, component, { props: { profile: 'document', modelValue: '<p>Table</p>' } })
  await page.locator('[data-editor-surface] p').click(); await page.keyboard.press('End')
  await page.getByRole('button', { name: 'Insert table', exact: true }).click()
  await expect(page.locator('[data-editor-surface] td')).toHaveCount(9)
  await page.locator('td').first().click(); await page.keyboard.type('Cell')
  await page.getByRole('toolbar', { name: 'Contextual actions', exact: true }).getByRole('button', { name: 'Add row', exact: true }).click()
  await expect(page.locator('td')).toHaveCount(12)
  await page.keyboard.press('Control+z'); await expect(page.locator('td')).toHaveCount(9)
  const saved = await lastValue(page); expect(saved).toContain('Cell')
  await page.evaluate(saved => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: { profile: 'document', modelValue: saved } }), saved)
  await expect(page.locator('[data-editor-surface] td')).toHaveCount(9)
  await expect(page.locator('[data-editor-surface] .embedded-code-widget')).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ readonly: true }))
  await expect(page.getByRole('button', { name: 'Bold', exact: true })).toBeDisabled()
  await expect(page.locator('[data-editor-surface] td').first()).toContainText('Cell')
  expect(await lastValue(page)).toBeUndefined()
})
