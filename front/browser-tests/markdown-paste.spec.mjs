import { test, expect, mount } from './fixtures.mjs'

const component = 'core/util/components/RichTextEditor.vue'
const markdown = '# Report\n\nSome **bold** and *italic* with `inline code`.\n\n- First\n- Second\n- [ ] Pending\n- [x] Done\n\n> A quotation\n\n| Name | Value |\n| --- | --- |\n| Sample | 42 |\n\n[Reference](https://example.org)\n\n```html\n<p>Literal code</p>\n```'
const lastValue = page => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)
async function paste(page, text, html = '') {
  await page.getByRole('textbox', { name: 'Content', exact: true }).evaluate((root, { text, html }) => {
    const data = new DataTransfer()
    data.setData('text/plain', text)
    if (html) data.setData('text/html', html)
    root.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
  }, { text, html })
}

for (const profile of ['document', 'rich-text']) test(`Markdown paste becomes editable HTML and survives reopening in ${profile}`, async ({ page }) => {
  await mount(page, component, { props: { profile, modelValue: '' } })
  const editor = page.getByRole('textbox', { name: 'Content', exact: true })
  await editor.click()
  await paste(page, markdown)
  await expect(editor.locator('h1')).toHaveText('Report')
  await expect(editor.locator('strong').filter({ hasText: /^bold$/ })).toHaveText('bold')
  await expect(editor.locator('i,em')).toHaveText('italic')
  await expect(editor.locator('li')).toHaveText(['First', 'Second', '☐ Pending', '☑ Done'])
  await expect(editor.locator('blockquote')).toHaveText('A quotation')
  await expect(editor.locator('td').last()).toHaveText('42')
  await expect(editor.locator('a')).toHaveAttribute('href', 'https://example.org')
  await expect(editor.locator('pre code')).toContainText('<p>Literal code</p>')
  const saved = await lastValue(page)
  expect(saved).not.toContain('galaris-raw-html')
  await page.keyboard.press('Control+z')
  await expect(editor).toHaveText('')
  await page.evaluate(({ profile, saved }) => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: { profile, modelValue: saved } }), { profile, saved })
  await expect(editor.locator('h1')).toHaveText('Report')
  await editor.locator('h1').click(); await page.keyboard.press('End'); await page.keyboard.type(' edited')
  expect(await lastValue(page)).toContain('Report edited')
})

test('Markdown copied with a source HTML wrapper is converted, while formatted HTML keeps precedence', async ({ page }) => {
  await mount(page, component, { props: { profile: 'document', modelValue: '' } })
  const editor = page.getByRole('textbox', { name: 'Content', exact: true })
  await editor.click()
  await paste(page, '## Heading\n\n**Important**', '<pre><span>## Heading\n\n**Important**</span></pre>')
  await expect(editor.locator('h2')).toHaveText('Heading')
  await expect(editor.locator('strong')).toHaveText('Important')
  await page.evaluate(() => window.testApp.setProps({ modelValue: '' }))
  await editor.click()
  await paste(page, '**Literal markers**', '<p><strong>**Literal markers**</strong></p>')
  await expect(editor.locator('strong')).toHaveText('**Literal markers**')
})

test('Markdown stays literal in code blocks and Source mode', async ({ page }) => {
  await mount(page, component, { props: { profile: 'document', modelValue: '<pre><code class="language-markdown">Example\n</code></pre>' } })
  const editor = page.getByRole('textbox', { name: 'Content', exact: true })
  await editor.locator('pre').click(); await page.keyboard.press('Control+End')
  await paste(page, markdown)
  await expect.poll(() => page.evaluate(() => {
    const saved = window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value ?? ''
    return new DOMParser().parseFromString(saved, 'text/html').querySelector('pre code')?.textContent
  })).toContain(markdown)
  await expect(editor.locator('h1,table,strong')).toHaveCount(0)
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  const source = page.locator('.ck-source-editing-area textarea')
  await source.fill('')
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.evaluate(text => navigator.clipboard.writeText(text), markdown)
  await source.press('Control+v')
  await expect(source).toHaveValue(markdown)
})

test('Markdown pasted into inline code remains literal', async ({ page }) => {
  await mount(page, component, { props: { profile: 'document', modelValue: '<p><code>Example</code></p>' } })
  const editor = page.getByRole('textbox', { name: 'Content', exact: true })
  await editor.locator('code').click(); await page.keyboard.press('End')
  await paste(page, '**literal**')
  await expect(editor.locator('code')).toContainText('**literal**')
  await expect(editor.locator('strong')).toHaveCount(0)
})

test('ordinary prose and unsafe Markdown links keep their text without active content', async ({ page }) => {
  await mount(page, component, { props: { profile: 'document', modelValue: '' } })
  const editor = page.getByRole('textbox', { name: 'Content', exact: true })
  await editor.click()
  await paste(page, 'An ordinary sentence with snake_case_name and 2 * 3 = 6.')
  await expect(editor).toHaveText('An ordinary sentence with snake_case_name and 2 * 3 = 6.')
  await expect(editor.locator('strong,em')).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ modelValue: '' }))
  await editor.click()
  await paste(page, '# Safe\n\n[Bad](javascript:alert%281%29)\n\n<script>window.markdownRan=true</script>')
  await expect(editor.locator('h1')).toHaveText('Safe')
  await expect(editor).toContainText('Bad')
  expect(await lastValue(page)).not.toMatch(/javascript:|<script|galaris-raw-html/)
  expect(await page.evaluate(() => window.markdownRan)).toBeUndefined()
})
