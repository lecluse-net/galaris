import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const corpus = '<h2>Été</h2><p><u>Underlined</u> <mark data-color="#fff59d" style="background-color: #fff59d">highlight</mark></p><ol start="3"><li><p>First</p><ul><li><p>Nested</p></li></ul></li></ol><table><tbody><tr><th colspan="2" colwidth="120,180"><p>Header</p></th></tr><tr><td><p>Left</p></td><td><p>Right</p></td></tr></tbody></table><pre><code class="language-html">  &lt;p&gt;\n    a  b\n</code></pre>'
const lastValue = page => page.evaluate(() => window.testApp.events.filter(value => value.name === 'update:modelValue').at(-1)?.value)

test('rich corpus survives actual editing, reopening and reading', async ({ page }) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: corpus, ariaLabel: 'Editorial content' } })
  const editor = page.getByRole('textbox', { name: 'Editorial content' })
  await expect(editor.locator('u')).toHaveText('Underlined')
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  await expect(editor.locator('ol')).toHaveAttribute('start', '3')
  await editor.locator('h2').click()
  await page.keyboard.press('End')
  await page.keyboard.type('!')
  const saved = await lastValue(page)
  expect(saved).toContain('<u>Underlined</u>')
  expect(saved).toContain('colspan="2"')
  expect(saved).toContain('  &lt;p&gt;\n    a  b\n')
  await page.evaluate(value => window.testApp.setProps({ modelValue: value }), saved)
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  await page.evaluate(value => window.testApp.mount({ component: 'core/util/components/RichText.vue', props: { content: value } }), saved)
  await expect(page.locator('.rich-content u')).toHaveText('Underlined')
  await page.evaluate(value => { window.richSaved = value }, saved)
})

test('reader rejects active HTML, remote images and unsafe links', async ({ page }) => {
  await mount(page, 'core/util/components/RichText.vue', { props: { profile: 'rich-text', content: '<script>window.xss = true</script><p onclick="window.xss = true">Safe</p><a href="javascript:alert(1)">Bad</a><img src="https://example.invalid/tracker.png">' } })
  await expect(page.locator('.rich-content')).toContainText('Safe')
  await expect(page.locator('.rich-content script,.rich-content img')).toHaveCount(0)
  await expect(page.locator('.rich-content a')).not.toHaveAttribute('href')
  expect(await page.evaluate(() => window.xss)).toBeUndefined()
})


const uri = 'document://00000000-0000-0000-0000-000000000001/attachments/00000000-0000-0000-0000-000000000002'
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX9sAAAAASUVORK5CYII='
async function command(page, name) {
  const button = page.getByRole('button', { name, exact: typeof name === 'string' }).first()
  if (!await button.isVisible()) await page.getByRole('button', { name: 'Show more items', exact: true }).click()
  await button.click()
}
async function imageEditor(page) {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '', profile: 'document', ariaLabel: 'Editorial content' } })
  await expect(page.locator('.ck-editor__editable')).toBeVisible()
  await page.evaluate(({uri,png}) => window.testApp.setProps({
    resolveImage: async () => new Blob([Uint8Array.from(atob(png), value => value.charCodeAt(0))], { type: 'image/png' }),
    modelValue: '<p>Before picture</p><figure class="image"><img width="200" alt="Example image" src="'+uri+'"></figure><p>After picture</p>',
  }), {uri,png})
  await expect(page.locator('.ck-editor__editable img')).toHaveAttribute('src', /^blob:/)
  await expect(page.locator('.ck-editor__editable img')).toHaveJSProperty('complete', true)
  await page.locator('.ck-editor__editable img').click()
}

test('native image handles resize, undo, captions and reopening retain the attachment', async ({ page }, testInfo) => {
  await imageEditor(page)
  const knob = page.locator('.ck-widget__resizer__handle-bottom-right')
  await expect(knob).toBeVisible()
  const before = await page.locator('.ck-editor__editable img').boundingBox()
  const box = await knob.boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2 + 80, { steps: 8 })
  await page.mouse.up()
  const resized = await lastValue(page)
  expect(resized).toMatch(/width: [0-9.]+%/)
  expect(resized).toContain(uri)
  expect(resized).not.toMatch(/blob:|data:image|contenteditable|ck-widget/)
  await command(page, 'Undo')
  await expect.poll(async () => (await page.locator('.ck-editor__editable img').boundingBox()).width).toBeCloseTo(before.width, 0)
  await command(page, 'Redo')
  await page.locator('.ck-editor__editable img').click()
  await page.getByRole('button', { name: 'Toggle caption on', exact: true }).click()
  await page.locator('.ck-editor__editable figcaption').fill('Figure one')
  const saved = await lastValue(page)
  expect(saved).toContain('<figcaption>Figure one</figcaption>')
  await page.evaluate(value => window.testApp.setProps({ modelValue: value }), saved)
  await expect(page.locator('.ck-editor__editable figcaption')).toHaveText('Figure one')
  await page.screenshot({ path: testInfo.outputPath('native-image-controls.png') })
})

test('native image drag moves a single attachment without duplicating it', async ({ page }) => {
  await imageEditor(page)
  await page.locator('.ck-editor__editable figure.image').dragTo(page.getByText('After picture', { exact: true }), { targetPosition: { x: 90, y: 22 } })
  await expect.poll(() => lastValue(page)).toContain(uri)
  const saved = await lastValue(page)
  expect(saved.match(/<img/g)).toHaveLength(1)
  expect(saved.indexOf('<img')).toBeGreaterThan(saved.indexOf('After picture'))
})

test('native upload emits canonical HTML when the upload finishes and supports alternative text', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '<p>Illustrated document</p>', profile: 'document', ariaLabel: 'Editorial content' } })
  await expect(page.locator('.ck-editor__editable')).toBeVisible()
  await page.evaluate(({uri,png}) => window.testApp.setProps({
    uploadImage: async (file, signal, progress) => { window.imageUpload = { type: file.type, size: file.size }; progress(1); return uri },
    resolveImage: async () => new Blob([Uint8Array.from(atob(png), x => x.charCodeAt(0))], { type: 'image/png' }),
  }), {uri,png})
  await page.locator('.ck-editor__editable').click()
  const chooser = page.waitForEvent('filechooser')
  await command(page, 'Upload image from computer')
  await (await chooser).setFiles({ name: 'blue.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64') })
  await expect.poll(() => lastValue(page)).toContain(uri)
  await page.locator('.ck-editor__editable img').click()
  await page.getByRole('button', { name: 'Change image text alternative', exact: true }).click()
  await page.getByRole('textbox', { name: 'Text alternative', exact: true }).fill('A blue square')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  expect(await lastValue(page)).toContain('alt="A blue square"')
  expect(await lastValue(page)).not.toMatch(/blob:|data:image/)
  expect(await page.evaluate(() => window.imageUpload.type)).toBe('image/png')
})

test('native tables allow rows, merge/split, properties and column resizing', async ({ page }, testInfo) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '<table><tbody><tr><td>One</td><td>Two</td></tr><tr><td>Three</td><td>Four</td></tr></tbody></table>', ariaLabel: 'Editorial content' } })
  const cells = page.locator('.ck-editor__editable td')
  await cells.first().click()
  const tools = page.getByRole('toolbar', { name: 'Table toolbar', exact: true })
  await expect(tools).toBeVisible()
  await tools.getByRole('button', { name: 'Row', exact: true }).click()
  await page.getByRole('button', { name: 'Insert row below', exact: true }).click()
  await expect(page.locator('.ck-editor__editable tr')).toHaveCount(3)
  await tools.getByRole('button', { name: 'Row', exact: true }).click()
  await page.getByRole('button', { name: 'Delete row', exact: true }).click()
  await expect(page.locator('.ck-editor__editable tr')).toHaveCount(2)
  await cells.first().click()
  await tools.getByRole('button', { name: 'Merge cells', exact: true }).nth(1).click()
  await page.getByRole('button', { name: 'Merge cell right', exact: true }).click()
  await expect(cells.first()).toHaveAttribute('colspan','2')
  await tools.getByRole('button', { name: 'Merge cells', exact: true }).nth(1).click()
  await page.getByRole('button', { name: 'Split cell vertically', exact: true }).click()
  await expect(cells).toHaveCount(4)
  const grip = page.locator('.ck-table-column-resizer').first()
  const box = await grip.boundingBox()
  await page.mouse.move(box.x + box.width/2, box.y + 10)
  await page.mouse.down()
  await page.mouse.move(box.x + 65, box.y + 10, {steps: 8})
  await page.mouse.up()
  const saved = await lastValue(page)
  expect(saved).toContain('<colgroup>')
  expect(saved).toMatch(/width: [0-9.]+%/)
  await page.evaluate(value => window.testApp.setProps({modelValue:value}), saved)
  await expect(page.locator('.ck-editor__editable col')).toHaveCount(2)
  await cells.first().click()
  await tools.getByRole('button', { name: 'Cell properties', exact: true }).click()
  await expect(page.getByRole('group', {name:'Dimensions',exact:true}).getByRole('textbox', { name: 'Width', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.screenshot({path:testInfo.outputPath('native-table-controls.png')})
})

for (const profile of ['rich-text', 'document']) test(`native source editing, fullscreen and read-only mode preserve ${profile} content`, async ({page}) => {
  await mount(page,'core/util/components/RichTextEditor.vue',{props:{profile,modelValue:'<p>Original</p>',ariaLabel:'Editorial content'}})
  const reading = page.getByRole('group', { name: 'Reading', exact: true })
  await expect(reading.getByRole('button', { name: 'Full width', exact: true })).toHaveCount(profile === 'document' ? 1 : 0)
  await command(page, 'Source')
  await page.locator('.ck-source-editing-area textarea').fill('<h3>Edited source</h3><p><sup>2</sup></p>')
  await command(page, 'Source')
  await expect(page.locator('.ck-editor__editable h3')).toHaveText('Edited source')
  expect(await lastValue(page)).toContain('<sup>2</sup>')
  const saved = await lastValue(page)
  await reading.getByRole('button', { name: /Enter fullscreen mode/ }).click()
  await expect(page.getByRole('textbox', { name: 'Editorial content' }).locator('h3')).toHaveText('Edited source')
  await page.getByRole('button', { name: /Leave fullscreen mode/ }).click()
  expect(await lastValue(page)).toBe(saved)
  await page.evaluate(()=>window.testApp.setProps({readonly:true}))
  await expect(page.locator('.ck-editor__editable')).toHaveAttribute('contenteditable','false')
  await expect(page.getByRole('button',{name:'Bold',exact:true})).toBeDisabled()
  await expect(reading.getByRole('button', { name: 'Source', exact: true })).toBeDisabled()
  await reading.getByRole('button', { name: /Enter fullscreen mode/ }).click()
  await expect(page.getByRole('textbox', { name: 'Editorial content' })).toHaveAttribute('contenteditable', 'false')
  expect(await lastValue(page)).toBe(saved)
})

test('pasted active HTML and external images cannot execute or fetch before saving', async ({page}) => {
  let fetched = false
  await page.route('https://example.invalid/**', route => { fetched=true; return route.abort() })
  await mount(page,'core/util/components/RichTextEditor.vue',{props:{modelValue:'<p>Before</p>',profile:'document',ariaLabel:'Editorial content'}})
  await page.locator('.ck-editor__editable').click()
  await page.locator('.ck-editor__editable').evaluate(root=>{
    const transfer = new DataTransfer()
    transfer.setData('text/html','<style>@import url("https://example.invalid/tracker.css"); p{background-image:url("https://example.invalid/bg.png")}</style><p onclick="window.xss=true">Pasted</p><img src="https://example.invalid/tracker.png" alt="Missing illustration"><script>window.xss=true</script>')
    root.dispatchEvent(new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true,cancelable:true}))
  })
  await expect(page.locator('.ck-editor__editable')).toContainText('Pasted')
  await expect(page.locator('.ck-editor__editable')).toContainText('Missing illustration')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('The content was pasted, but some images could not be imported.', { exact: false })).toBeVisible()
  expect(await lastValue(page)).not.toMatch(/onclick|<img/)
  expect(fetched).toBe(false)
  expect(await page.evaluate(()=>window.xss)).toBeUndefined()
})
test('internal links have native application hrefs but persist canonical identities', async ({ page }) => {
  const uri = 'galaris://goal/00000000-0000-0000-0000-000000000123'
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: `<p><a href="${uri}">My goal</a> remains here.</p>`, ariaLabel: 'Editorial content' } })
  const editor = page.getByRole('textbox', { name: 'Editorial content' })
  await expect(editor.locator('a')).toHaveAttribute('href', '/goal?goal_id=00000000-0000-0000-0000-000000000123')
  await editor.click()
  await page.keyboard.press('End')
  await page.keyboard.type('!')
  const saved = await lastValue(page)
  expect(saved).toContain(`href="${uri}"`)
  expect(saved).not.toContain('data-rich-reference')
  await page.evaluate(value => window.testApp.mount({ component: 'core/util/components/RichText.vue', props: { content: value } }), saved)
  await expect(page.locator('.rich-content a')).toHaveAttribute('href', '/goal?goal_id=00000000-0000-0000-0000-000000000123')
})

test('large documents remain editable in dark mobile and light desktop layouts', async ({ page }) => {
  const body = Array.from({ length: 1200 }, (_, index) => `<p>Section ${index}: Écrire et conserver les caractères accentués.</p>`).join('')
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: body, ariaLabel: 'Editorial content' }, dark: true })
  const editor = page.getByRole('textbox', { name: 'Editorial content' })
  await expect(editor.locator('p')).toHaveCount(1200)
  await editor.locator('p').first().click()
  await page.keyboard.press('Home')
  await page.keyboard.type('Checked ')
  expect((await lastValue(page)).length).toBeGreaterThan(70000)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(editor).toBeEditable()
  await expect(editor.locator('p')).toHaveCount(1200)
  await editor.locator('p').first().click()
  await page.keyboard.press('Control+Home')
  await page.keyboard.type('Mobile ')
  expect(await lastValue(page)).toContain('Mobile Checked Section 0')
  await page.setViewportSize({ width: 1280, height: 900 })
  await command(page, /Enter fullscreen mode/); await expect(page.locator('body')).toHaveClass(/ck-fullscreen/)
})

for (const editing of [false, true]) {
  test(`${editing ? 'editor' : 'reader'} keeps readable HTML contrast when the application theme changes`, async ({ page }) => {
    const content = `${corpus}<p><a href="https://example.com">A link</a> and <code>inline code</code>.</p><blockquote><p>Quotation</p></blockquote><p><span style="background-color: #90caf9"><strong>Highlighted text</strong></span></p>`
    await mount(page, editing ? 'core/util/components/RichTextEditor.vue' : 'core/util/components/EditorialContent.vue', {
      props: editing ? { profile: 'document', modelValue: content, ariaLabel: 'Editorial content' } : { content, mediaType: 'text/html' },
    })
    // Quasar's dark-page token exists even in light mode; hosts may set their own ink.
    await page.evaluate(() => {
      document.body.style.setProperty('--q-dark-page', '#000000')
      document.querySelector('.rich-content').parentElement.style.color = '#000000'
    })
    for (const dark of [false, true, false]) {
      await page.evaluate(dark => window.testApp.dark(dark), dark)
      await expect(page.locator('body')).toHaveClass(dark ? /body--dark/ : /body--light/)
      if (editing) await command(page, /(?:Enter|Leave) fullscreen mode/)
      const results = await page.locator('.rich-content').evaluate(root => {
        const rgb = color => color.match(/[\d.]+/g).slice(0, 3).map(Number)
        const luminance = color => rgb(color).map(value => {
          const channel = value / 255
          return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
        }).reduce((sum, channel, index) => sum + channel * [.2126, .7152, .0722][index], 0)
        const background = element => {
          if (!element) return 'rgb(255, 255, 255)'
          const color = getComputedStyle(element).backgroundColor
          const channels = color.match(/[\d.]+/g).map(Number)
          const alpha = channels[3] ?? 1
          if (alpha === 1) return color
          const behind = rgb(background(element.parentElement))
          return 'rgb(' + channels.slice(0,3).map((value,index) => value * alpha + behind[index] * (1-alpha)).join(',') + ')'
        }
        const nodes = [...root.querySelectorAll('h2,p,li,a,th,td,pre,code,mark,span,strong,blockquote')]
        const toolbar = document.querySelector('.ck-toolbar')
        if (toolbar) nodes.push(toolbar)
        return {
          background: luminance(background(root)),
          contrasts: nodes.map(node => {
            const foreground = luminance(getComputedStyle(node).color)
            const backdrop = luminance(background(node))
            return { tag: node.outerHTML, ratio: (Math.max(foreground, backdrop) + .05) / (Math.min(foreground, backdrop) + .05) }
          }),
        }
      })
      expect(results.background)[dark ? 'toBeLessThan' : 'toBeGreaterThan'](dark ? .05 : .9)
      for (const { tag, ratio } of results.contrasts) expect(ratio, `${tag} in ${dark ? 'dark' : 'light'} mode`).toBeGreaterThanOrEqual(4.5)
      if (editing) await command(page, /(?:Enter|Leave) fullscreen mode/)
    }
    if (editing) expect(await lastValue(page)).toBeUndefined()
  })
}

for (const editing of [false, true]) {
  test(`${editing ? 'editor' : 'reader'} opens internal and external links in a new tab`, async ({ page, context }) => {
    const destination = '/goal?goal_id=00000000-0000-0000-0000-000000000123'
    const html = '<p><a target="_blank" href="galaris://goal/00000000-0000-0000-0000-000000000123">My goal</a></p><p><a target="_blank" href="https://example.com">External</a></p>'
    await mount(page, editing ? 'core/util/components/RichTextEditor.vue' : 'core/util/components/RichText.vue', { props: editing ? { modelValue: html } : { content: html } })
    const origin = await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)
    await context.route('**/goal?goal_id=*', route => route.fulfill({ contentType: 'text/html', body: 'Goal' }))
    await context.route('https://example.com/**', route => route.fulfill({ contentType: 'text/html', body: 'External' }))
    for (const name of ['My goal', 'External']) {
      const link = page.getByRole('link', { name, exact: true })
      await expect(link).toHaveAttribute('target', '_blank')
      const opened = context.waitForEvent('page')
      await link.click(editing ? { modifiers: ['Control'] } : {})
      const tab = await opened
      await expect.poll(() => tab.url()).toContain(name === 'My goal' ? destination : 'https://example.com')
      expect(await tab.evaluate(() => window.opener)).toBeNull()
      await tab.close()
      expect(await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(origin)
    }
    if (editing) {
      await page.getByRole('link', { name: 'My goal', exact: true }).click()
      await expect(page.locator('.ck-link-toolbar__preview')).toHaveAttribute('target', '_blank')
      const opened = context.waitForEvent('page')
      await page.locator('.ck-link-toolbar__preview').click()
      const tab = await opened
      await expect.poll(() => tab.url()).toContain(destination)
      await tab.close()
      expect(await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe(origin)
    }
  })
}


test('native find and replace remains usable on desktop', async ({page}, testInfo)=>{
  await page.setViewportSize({width:1024,height:844})
  await mount(page,'core/util/components/RichTextEditor.vue',{props:{modelValue:'<p>Find me</p>',ariaLabel:'Editorial content'},dark:true})
  await command(page,'Find and replace')
  await page.getByRole('textbox', {name:'Find in text…',exact:true}).fill('Find')
  await page.getByRole('button', {name:'Find',exact:true}).click()
  await page.getByRole('textbox', {name:'Replace with…',exact:true}).fill('Found')
  await page.getByRole('button', {name:'Replace',exact:true}).click()
  await expect(page.locator('.ck-editor__editable')).toContainText('Found me')
  expect(await lastValue(page)).toBe('<p>Found me</p>')
  await page.screenshot({path:testInfo.outputPath('native-desktop-search.png')})
})

test('native link form accepts focus inside a Quasar dialog and the backdrop stays dismissible', async ({page}) => {
  await jsonRoute(page, '**/api/agents**', [])
  await mount(page, 'app/task/components/TaskFormDialog.vue', {props:{modelValue:true}, privileges:['TASK_EDIT']})
  const editable = page.locator('.ck-editor__editable')
  await editable.fill('Example')
  await page.keyboard.press('Control+a')
  await page.keyboard.press('Control+k')
  const input = page.getByRole('textbox', {name:'Link URL',exact:true})
  await input.fill('https://example.com')
  await expect(input).toBeFocused()
  await page.getByRole('button', {name:'Insert',exact:true}).click()
  await expect(editable.locator('a')).toHaveAttribute('href','https://example.com')
  await page.locator('.q-dialog__backdrop').click({position:{x:3,y:3}})
  await expect.poll(()=>lastValue(page)).toBe(false)
})

test('changing profile keeps reading tools available and reserves document insertion and page layout', async ({page}) => {
  await mount(page, 'core/util/components/RichTextEditor.vue', {props:{modelValue:'<p>Text remains</p>',profile:'document'}})
  await expect(page.locator('.ck-editor__editable')).toBeVisible()
  await expect(page.locator('input[type=file]').first()).toBeAttached()
  await expect(page.getByRole('button', {name:'Galaris link',exact:true})).toBeVisible()
  await expect(page.getByRole('button', {name:'Source',exact:true})).toBeVisible()
  await page.evaluate(()=>window.testApp.setProps({profile:'rich-text'}))
  await expect(page.locator('input[type=file]')).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable')).toHaveText('Text remains')
  await expect(page.getByRole('button', {name:'Galaris link',exact:true})).toHaveCount(0)
  await expect(page.getByRole('button', {name:'Source',exact:true})).toBeVisible()
  await expect(page.getByRole('button', {name:/Enter fullscreen mode/})).toBeVisible()
  await expect(page.getByRole('button', {name:'Full width',exact:true})).toHaveCount(0)
  await expect(page.getByRole('button', {name:'Document images',exact:true})).toHaveCount(0)
})
