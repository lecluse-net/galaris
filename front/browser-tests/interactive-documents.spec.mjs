import { test, expect, mount, editorHtml } from './fixtures.mjs'
test('scripts stay out of the host and documents offer no Source view', async ({ page }) => {
 const html='<p>Archived</p><script type="module">window.documentScriptRan = true;</script>'
 await mount(page,'core/util/components/RichTextEditor.vue',{props:{profile:'document',modelValue:html}})
 await expect(page.locator('[data-editor-surface]')).toContainText('Archived')
 await expect(page.locator('[data-editor-surface]')).not.toContainText('window.documentScriptRan')
 await expect(page.getByRole('button',{name:'Source',exact:true})).toHaveCount(0)
 expect(await editorHtml(page)).toContain('<script type="module">window.documentScriptRan = true;</script>')
 expect(await page.evaluate(()=>window.documentScriptRan)).toBeUndefined()
 await page.evaluate(content=>window.testApp.mount({component:'core/util/components/RichText.vue',props:{profile:'document',content}}),html)
 await expect(page.locator('.rich-content')).not.toContainText('window.documentScriptRan')
 await expect(page.locator('.rich-content script,iframe')).toHaveCount(0)
 expect(await page.evaluate(()=>window.documentScriptRan)).toBeUndefined()
})
test('existing full HTML remains preserved without running scripts in the editor', async ({page})=>{
 await mount(page,'core/util/components/RichTextEditor.vue',{props:{profile:'document',modelValue:'<!doctype html><html><body><h1>Page</h1><script>window.ran=true</script></body></html>'}})
 await expect(page.getByRole('dialog')).toHaveCount(0)
 await expect(page.locator('[data-editor-surface]')).toContainText('Page')
 expect(await editorHtml(page)).toContain('window.ran=true')
 expect(await page.evaluate(()=>window.ran)).toBeUndefined()
})

test('Dataset links remain distinct canonical references in authored HTML', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000005'
  const content = `<p><a href="data://${id}">Synthetic Dataset</a></p>`
  await mount(page, 'core/util/components/RichText.vue', { props: { profile: 'document', content } })
  await expect(page.getByRole('link', { name: 'Synthetic Dataset', exact: true })).toHaveAttribute('href', `/dataset/${id}`)
})
