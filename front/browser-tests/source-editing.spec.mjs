import { test, expect, mount } from './fixtures.mjs'

const editorComponent = 'core/util/components/RichTextEditor.vue'
const sourceButton = page => page.getByRole('button', { name: 'Source', exact: true })
const sourceInput = page => page.locator('.ck-source-editing-area textarea')

for (const dark of [false, true]) {
  test(`source editing preserves text, undo and inert syntax highlighting in ${dark ? 'dark' : 'light'} mode`, async ({ page }, testInfo) => {
    await mount(page, editorComponent, { dark, props: { profile: 'document', modelValue: '<p>Original</p>' } })
    await sourceButton(page).click()
    const input = sourceInput(page)
    const preview = page.locator('.galaris-source-highlight')
    const source = '<p><a href="https://example.org/?x=1&amp;y=2">Updated &lt;tag&gt;</a></p>\n<script type="module">const greeting = "hello"; window.__sourceExecuted = true;</script>\n<style>.example { color: red; }</style>\n<!-- A comment -->\n'
    await input.fill(source)
    await expect(input).toHaveCSS('font-family', /monospace/)
    await expect(preview).toHaveAttribute('aria-hidden', 'true')
    expect(await preview.textContent()).toBe(source + ' ')
    await expect(preview.locator('.hljs-name').first()).toHaveText('p')
    await expect(preview.locator('.hljs-attr').first()).toHaveText('href')
    await expect(preview.locator('.language-javascript .hljs-keyword').first()).toHaveText('const')
    await expect(preview.locator('.language-css .hljs-attribute').first()).toHaveText('color')
    expect(await preview.locator('script, style, a').count()).toBe(0)
    expect(await page.evaluate(() => window.__sourceExecuted)).toBeUndefined()
    const tokenColors = await preview.evaluate(element => ['.hljs-name', '.hljs-attr', '.hljs-string'].map(selector => getComputedStyle(element.querySelector(selector)).color))
    expect(new Set(tokenColors).size).toBe(3)
    // Native selection/caret are preserved while the separate highlight layer updates.
    await input.press('Control+Home')
    await page.keyboard.type(' ')
    expect(await input.inputValue()).toBe(' ' + source)
    expect(await input.evaluate(element => element.selectionStart)).toBe(1)
    expect(await preview.textContent()).toBe(' ' + source + ' ')
    await input.press('Control+z')
    await expect(input).toHaveValue(source)
    expect(await preview.textContent()).toBe(source + ' ')
    await page.screenshot({ path: testInfo.outputPath(`source-${dark ? 'dark' : 'light'}.png`) })
    await input.fill('<h3>Edited source</h3><p>Content &amp; text</p>')
    await sourceButton(page).click()
    await expect(page.locator('.ck-editor__editable h3')).toHaveText('Edited source')
    await expect(preview).toHaveCount(0)
    const saved = await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.args[0])
    expect(saved).toContain('<h3>Edited source</h3>')
    expect(saved).not.toMatch(/hljs-|galaris-source-highlight/)
    await sourceButton(page).click()
    await expect(preview).toHaveCount(1)
    await expect(input).toHaveValue(/Edited source/)
    await page.evaluate(() => window.testApp.setProps({ readonly: true }))
    await expect(input).toHaveAttribute('readonly', '')
    await expect(preview).toBeVisible()
  })
}

test('source text and highlighting keep matching geometry for long lines and fullscreen', async ({ page }, testInfo) => {
  await mount(page, editorComponent, { props: { profile: 'document', modelValue: '<p>Original</p>' } })
  await sourceButton(page).click()
  const input = sourceInput(page)
  const value = '<p>' + 'a long line &amp; more text '.repeat(80) + '</p>\n\t<p>Indented</p>\n'
  await input.fill(value)
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    const measurements = await input.evaluate(element => {
      const overlay = element.parentElement.querySelector('.galaris-source-highlight')
      return [element, overlay].map(node => {
        const style = getComputedStyle(node)
        const rect = node.getBoundingClientRect()
        return { width: rect.width, height: rect.height, scrollHeight: node.scrollHeight, padding: style.padding, font: style.font, tabSize: style.tabSize, whiteSpace: style.whiteSpace }
      })
    })
    expect(measurements[0]).toEqual(measurements[1])
    expect(await page.locator('.galaris-source-highlight').textContent()).toBe(value + ' ')
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  // CKEditor disables the fullscreen command while Source mode is active.
  await sourceButton(page).click()
  await page.getByRole('button', { name: /Enter fullscreen mode/ }).click()
  await sourceButton(page).click()
  await input.fill(value)
  await expect(page.locator('.galaris-source-highlight')).toHaveCount(1)
  await expect(input).toHaveValue(value)
  await page.screenshot({ path: testInfo.outputPath('source-fullscreen.png') })
  await sourceButton(page).click()
  await expect(page.locator('.ck-editor__editable p').last()).toHaveText('Indented')
})
