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
test('full HTML source offers a choice and cancelling preserves the document', async ({page})=>{
 await mount(page,'core/util/components/RichTextEditor.vue',{props:{profile:'document',modelValue:'<p>Keep me</p>'}})
 await page.getByRole('button',{name:'Source',exact:true}).click()
 await page.locator('.ck-source-editing-area textarea').fill('<!doctype html><html><body><h1>Page</h1><script>window.ran=true</script></body></html>')
 await page.getByRole('button',{name:'Source',exact:true}).click()
 await expect(page.getByText('This page exceeds the rich text format')).toBeVisible()
 await page.getByRole('button',{name:'Cancel',exact:true}).click()
 await expect(page.locator('.ck-editor__editable')).toHaveText('Keep me')
 expect(await page.evaluate(()=>window.ran)).toBeUndefined()
})
