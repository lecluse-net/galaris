import { test, expect, mount } from './fixtures.mjs'
test('scripts stay out of the host and their source is visible only in Source mode', async ({ page }) => {
 const html='<p>Archived</p><script type="module">window.documentScriptRan = true;</script>'
 await mount(page,'core/util/components/RichTextEditor.vue',{props:{profile:'document',modelValue:html}})
 await expect(page.locator('.ck-editor__editable')).toContainText('Archived')
 await expect(page.locator('.ck-editor__editable')).not.toContainText('window.documentScriptRan')
 await page.getByRole('button',{name:'Source',exact:true}).click()
 await expect(page.locator('.ck-source-editing-area textarea')).toHaveValue(/<script type="module">window.documentScriptRan = true;<\/script>/)
 expect(await page.evaluate(()=>window.documentScriptRan)).toBeUndefined()
 await page.evaluate(content=>window.testApp.mount({component:'core/util/components/RichText.vue',props:{profile:'document',content}}),html)
 await expect(page.locator('.rich-content')).not.toContainText('window.documentScriptRan')
 await expect(page.locator('.rich-content script,iframe')).toHaveCount(0)
 expect(await page.evaluate(()=>window.documentScriptRan)).toBeUndefined()
})
test('explicit full HTML source stays available without running scripts in the editor', async ({page})=>{
 await mount(page,'core/util/components/RichTextEditor.vue',{props:{profile:'document',modelValue:'<p>Keep me</p>'}})
 await page.getByRole('button',{name:'Source',exact:true}).click()
 await page.locator('.ck-source-editing-area textarea').fill('<!doctype html><html><body><h1>Page</h1><script>window.ran=true</script></body></html>')
 await page.getByRole('button',{name:'Source',exact:true}).click()
 await expect(page.getByRole('dialog')).toHaveCount(0)
 await expect(page.locator('.ck-editor__editable')).toContainText('Page')
 await page.getByRole('button',{name:'Source',exact:true}).click()
 await expect(page.locator('.ck-source-editing-area textarea')).toHaveValue(/window.ran=true/)
 expect(await page.evaluate(()=>window.ran)).toBeUndefined()
})

test('Dataset links remain distinct canonical references in authored HTML', async ({ page }) => {
  const id = '00000000-0000-4000-8000-000000000005'
  const content = `<p><a href="data://${id}">Synthetic Dataset</a></p>`
  await mount(page, 'core/util/components/RichText.vue', { props: { profile: 'document', content } })
  await expect(page.getByRole('link', { name: 'Synthetic Dataset', exact: true })).toHaveAttribute('href', `/dataset/${id}`)
})
