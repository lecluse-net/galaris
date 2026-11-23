import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document } from './data.mjs'

async function fixture(page, content) {
  let item = { ...document, content_profile: 'document', media_type: 'text/html', payload: { text: content } }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/attachments?*', [])
  await page.route(/\/api\/documents\/doc-a(?:\?.*)?$/, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { item, agent_id: 7 } })
    item = { ...item, ...route.request().postDataJSON(), revision: item.revision + 1 }
    return route.fulfill({ json: item })
  })
  return () => item.payload.text
}

const mountEditor = page => mount(page, 'app/document/components/DocumentEditor.vue', {
  props: { documentId: 'doc-a', agentId: 7 }, privileges: ['DOCUMENT_EDIT'],
})

test.describe('document editing on touch screens', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })

  test('editing between styled SVG figures preserves their sources and captions on reopen and export', async ({ page }) => {
    const svg = name => `<svg viewBox="0 0 160 80" width="160" height="80" aria-label="${name}"><style>.bar{fill:blue}</style><defs><rect id="bar" width="96" height="24"></rect></defs><use href="#bar" class="bar"></use></svg>`
    const before = svg('First chart'), after = svg('Second chart')
    const saved = await fixture(page, `<figure>${before}<figcaption>First caption</figcaption></figure><p>Between charts</p><figure>${after}<figcaption>Second caption</figcaption></figure>`)
    await mountEditor(page)
    const surface = page.getByRole('textbox', { name: 'Content', exact: true })
    const first = surface.getByRole('img', { name: 'First chart' })
    await expect(first).toBeVisible()
    await expect(first).toHaveJSProperty('naturalWidth', 160)
    expect(await first.evaluate(image => {
      const canvas = image.ownerDocument.createElement('canvas')
      const context = canvas.getContext('2d')
      context.drawImage(image, 0, 0)
      return Array.from(context.getImageData(10, 10, 1, 1).data)
    })).toEqual([0, 0, 255, 255])
    await expect(surface.getByRole('img', { name: 'Second chart' })).toBeVisible()
    await expect(surface.locator('iframe')).toHaveCount(0)
    await surface.getByText('Between charts', { exact: true }).tap()
    await page.keyboard.press('End')
    await page.keyboard.insertText(' edited')
    await expect.poll(saved).toContain('Between charts edited')
    await surface.getByText('First caption', { exact: true }).tap()
    await page.keyboard.press('End')
    await page.keyboard.insertText(' edited')
    await expect.poll(saved).toContain('First caption edited')
    expect(saved()).toContain(before)
    expect(saved()).toContain(after)

    await page.evaluate(() => window.testApp.unmount())
    await mountEditor(page)
    await expect(surface.getByText('Between charts edited', { exact: true })).toBeVisible()
    await expect(surface.getByText('First caption edited', { exact: true })).toBeVisible()
    await expect(first).toHaveJSProperty('naturalWidth', 160)

    let snapshot
    await page.route('**/api/documents/doc-a/export-pdf', route => {
      snapshot = route.request().postDataJSON().html
      return route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.7\nfixture' })
    })
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: 'More tools', exact: true }).tap()
    await page.getByRole('button', { name: 'Export as PDF', exact: true }).tap()
    await download
    const preview = await page.context().newPage()
    await preview.setContent(snapshot)
    await expect(preview.getByRole('img', { name: 'First chart' })).toHaveJSProperty('naturalWidth', 160)
    await expect(preview.getByRole('img', { name: 'Second chart' })).toHaveJSProperty('naturalWidth', 160)
    await expect(preview.getByText('Between charts edited', { exact: true })).toBeVisible()
    await expect(preview.getByText('First caption edited', { exact: true })).toBeVisible()
    await preview.close()
  })

  test('sections give separate responsive applications their own styles and leave the prose editable', async ({ page }) => {
    const block = label => `<section><style>section{display:grid;gap:8px}@media(max-width:480px){section{grid-template-columns:1fr}}</style><label>${label}<input></label><button>Apply</button><output>Ready</output><script>document.querySelector('button').onclick=()=>document.querySelector('output').textContent=document.querySelector('input').value</script></section>`
    await fixture(page, block('First answer') + '<p>Editable between applications</p>' + block('Second answer'))
    await mountEditor(page)
    const frames = page.locator('.document-application-frame')
    await expect(frames).toHaveCount(2)
    const left = frames.nth(0).contentFrame().frameLocator('iframe')
    const right = frames.nth(1).contentFrame().frameLocator('iframe')
    await expect(left.getByRole('textbox', { name: 'First answer' })).toBeVisible()
    await right.getByRole('textbox', { name: 'Second answer' }).fill('New value')
    await right.getByRole('button', { name: 'Apply' }).tap()
    await expect(right.getByRole('status')).toHaveText('New value')
    await expect(left.getByRole('status')).toHaveText('Ready')
    await expect(page.getByRole('textbox', { name: 'Content', exact: true }).getByText('Editable between applications')).toBeVisible()
  })
})
