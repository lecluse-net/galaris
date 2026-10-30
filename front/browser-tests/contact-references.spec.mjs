import { test, expect, mount, jsonRoute, editorHtml, setPrivileges } from './fixtures.mjs'
import { contactResource } from './data.mjs'

const uri = `galaris://contact/${contactResource.memory_item_id}`
const storedCard = `<blockquote class="galaris-link-card galaris-contact-card"><p><a href="${uri}"><strong>Synthetic Person</strong></a></p><p>${uri}</p></blockquote>`
const editorComponent = 'core/util/components/RichTextEditor.vue'
const readerComponent = 'core/util/components/RichText.vue'

async function fixtures(page) {
  let contact = structuredClone(contactResource), denied = false
  await jsonRoute(page, '**/api/contacts/defaults', { country: 'FR' })
  await page.route(`**/api/contacts/${contact.memory_item_id}`, route => {
    if (denied) return route.fulfill({ status: 404, json: { detail: 'Unavailable' } })
    if (route.request().method() === 'PATCH') contact = { ...contact, ...route.request().postDataJSON() }
    return route.fulfill({ json: contact })
  })
  return { deny: value => { denied = value }, contact: () => contact }
}

for (const width of [1440, 390]) test(`a Contact card inserts through Files, survives saving and opens its editor at ${width}px`, async ({ page }, testInfo) => {
  await fixtures(page)
  await page.setViewportSize({ width, height: 1000 })
  await jsonRoute(page, '**/api/agents/selection?*', [{ id: 7, label: 'Synthetic Agent', has_avatar: false }])
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'galaris', label: 'Galaris', native: true, capabilities: ['list'] }])
  await page.route('**/api/file-share/browser/entries?*', route => {
    const location = new URL(route.request().url()).searchParams.get('uri')
    return route.fulfill({ json: { uri: location, entries: location === 'galaris://' ? [{ uri: 'galaris://contact/', name: 'Contacts', is_collection: true, capabilities: ['info', 'list'] }] : [{ uri, name: 'Synthetic Person', is_collection: false,
      media_type: 'application/vnd.galaris.contact+json', size: null, capabilities: ['info', 'read'] }], truncated: false, next_cursor: null } })
  })
  await mount(page, editorComponent, { props: { modelValue: '<p>Keep authored text</p>', profile: 'document', resourceAgentId: 7 }, privileges: ['CONTACT_EDIT'] })
  const editor = page.locator('[data-editor-surface]')
  await editor.click(); await page.keyboard.press('End')
  await page.getByRole('button', { name: 'Galaris link', exact: true }).click()
  const picker = page.getByRole('dialog')
  await picker.getByRole('button', { name: 'Open Galaris', exact: true }).click()
  await picker.getByRole('button', { name: 'Open Contacts', exact: true }).click()
  await picker.getByRole('checkbox', { name: 'Select Synthetic Person', exact: true }).check()
  await picker.getByRole('button', { name: 'Select', exact: true }).click()
  await expect(picker).toHaveCount(0)
  const card = editor.locator('.galaris-contact-card')
  await expect(card).toContainText('synthetic@example.org')
  await expect(card).toContainText('+33 1 23 45 67 89')
  await expect(card).toContainText('Synthetic City')
  const stored = await editorHtml(page)
  expect(stored).toContain('galaris-contact-card')
  expect(stored).toContain(uri)
  expect(stored).toContain('Keep authored text')
  expect(stored).not.toMatch(/synthetic@example.org|Synthetic City|galaris-resource-embed|blob:/)
  await card.screenshot({ path: testInfo.outputPath('contact-card-light.png') })
  await page.evaluate(() => window.testApp.dark(true))
  await card.screenshot({ path: testInfo.outputPath('contact-card-dark.png') })

  await card.locator('p a').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Display name', { exact: true })).toHaveValue('Synthetic Person')
  await dialog.getByLabel('Phone number', { exact: true }).fill('+33 9 87 65 43 21')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(card).toContainText('+33 9 87 65 43 21')
  expect(await editorHtml(page)).toBe(stored)

  await mount(page, readerComponent, { props: { content: stored, profile: 'document' }, privileges: ['CONTACT_ACCESS'] })
  await expect(page.locator('.galaris-contact-card')).toContainText('+33 9 87 65 43 21')
  await page.locator('.galaris-contact-card p a').click()
  await expect(dialog.getByLabel('Display name', { exact: true })).toBeDisabled()
  await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await page.locator('.q-dialog__backdrop').last().click({ position: { x: 5, y: 5 } })
  await expect(dialog).toHaveCount(0)
  await setPrivileges(page, [])
  await expect(page.locator('.galaris-contact-card')).not.toContainText('synthetic@example.org')
  await expect(page.locator('.galaris-contact-card')).not.toContainText('+33 9 87 65 43 21')
})

test('Contact card conversion is reversible and denied reads never enter the saved document', async ({ page }) => {
  const source = await fixtures(page)
  await mount(page, editorComponent, { props: { profile: 'document', modelValue: `<p><a href="${uri}">Synthetic Person</a></p>` }, privileges: ['CONTACT_ACCESS'] })
  const editor = page.locator('[data-editor-surface]')
  await editor.locator('a').click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Show card', exact: true }).click()
  await expect(editor.locator('.galaris-contact-card')).toContainText('synthetic@example.org')
  await editor.locator('.galaris-contact-card > p').last().click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Show URL', exact: true }).click()
  await expect(editor.locator('.galaris-contact-card')).toHaveCount(0)
  source.deny(true)
  await editor.locator('a').click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Show card', exact: true }).click()
  // Reversing an existing card restores authored name/URI, then rechecks its
  // private details. A fresh conversion still requires a successful read.
  await expect(editor.locator('.galaris-contact-card').getByRole('alert')).toBeVisible()
  await expect(editor.locator('.galaris-contact-card')).not.toContainText('synthetic@example.org')
  expect(await editorHtml(page)).not.toContain('synthetic@example.org')
  await mount(page, editorComponent, { props: { profile: 'document', modelValue: `<p><a href="${uri}">Synthetic Person</a></p>` }, privileges: ['CONTACT_ACCESS'] })
  await editor.locator('a').click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Show card', exact: true }).click()
  await expect(editor.locator('.galaris-contact-card')).toHaveCount(0)
  expect(await editorHtml(page)).toContain(uri)
  await mount(page, readerComponent, { props: { content: storedCard, profile: 'document' }, privileges: ['CONTACT_ACCESS'] })
  await expect(page.getByRole('alert')).toContainText('Contacts could not be loaded.')
  await expect(page.locator('.galaris-contact-card')).not.toContainText('synthetic@example.org')
  source.deny(false)
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.locator('.galaris-contact-card')).toContainText('synthetic@example.org')
})

test('Contact exports include authorized details and recheck access before reusing a rendering', async ({ page }) => {
  const source = await fixtures(page)
  await mount(page, editorComponent, { privileges: ['CONTACT_ACCESS'] })
  await page.evaluate(async content => window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
    profile: 'document', modelValue: content,
    exportPdf: async html => { window.contactPdf = html; window.contactPdfCount = (window.contactPdfCount ?? 0) + 1; return new Blob(['%PDF-1.7 synthetic'], { type: 'application/pdf' }) },
  } }), storedCard)
  await expect(page.locator('.galaris-contact-card')).toContainText('synthetic@example.org')
  const button = page.getByRole('button', { name: 'Export as PDF', exact: true })
  await button.click()
  await expect.poll(() => page.evaluate(() => window.contactPdfCount)).toBe(1)
  expect(await page.evaluate(() => window.contactPdf)).toContain('synthetic@example.org')
  source.deny(true)
  await button.click()
  await expect(page.getByText('Unable to export the document as PDF. Check its images and try again.')).toBeVisible()
  expect(await page.evaluate(() => window.contactPdfCount)).toBe(1)
})

test('a Contact deep link opens its existing edit dialog without needing a directory page', async ({ page }) => {
  await fixtures(page)
  await jsonRoute(page, '**/api/agents/selection?*', [])
  await mount(page, 'app/memory/pages/contacts.vue', { route: `/memory/contacts?contact_id=${contactResource.memory_item_id}`, privileges: ['CONTACT_EDIT'] })
  await expect(page.getByRole('dialog').getByLabel('Display name', { exact: true })).toHaveValue('Synthetic Person')
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
