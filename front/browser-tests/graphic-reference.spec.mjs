import { test, expect, mount } from './fixtures.mjs'

test('the visual reference is available only for the exact dev environment', async ({ page }) => {
  for (const environment of ['prod', 'pp', 'test', 'demo', 'DEV', '', 'unknown']) {
    await mount(page, 'test-support/browser/GraphicReferenceHarness.vue', { props: { environment } })
    await expect(page.getByRole('heading', { name: 'Visual reference', exact: true })).toHaveCount(0)
  }
  await mount(page, 'test-support/browser/GraphicReferenceHarness.vue')
  await expect(page.getByRole('heading', { name: 'Visual reference', exact: true })).toBeVisible()
})

test('reference interactions remain local and the catalogue survives theme and viewport changes', async ({ page }, testInfo) => {
  await mount(page, 'test-support/browser/GraphicReferenceHarness.vue', { locale: 'fr' })
  await page.getByRole('button', { name: 'Ouvrir la modale', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Nom', { exact: true }).fill('Exemple synthétique')
  await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: 'Ouvrir la modale', exact: true }).click()
  await dialog.getByRole('button', { name: 'Fermer', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  const separator = page.getByRole('separator', { name: 'Redimensionner les panneaux' }).first()
  await separator.focus()
  const before = Number(await separator.getAttribute('aria-valuenow'))
  await separator.press('ArrowRight')
  await expect(separator).toHaveAttribute('aria-valuenow', String(before + 5))
  const glyphs = page.locator('#glyphs')
  for (const [family, name] of [['Illustrations', '/editor-icons/gnome/'], ['Emoji', 'emoji:1F600'], ['Material Design Icons', 'font:mdi:ab-testing'], ['Font Awesome', 'font:fab:']]) {
    await glyphs.getByRole('combobox', { name: 'Glyphes et illustrations', exact: true }).click()
    await page.getByRole('option', { name: family, exact: true }).click()
    await expect(glyphs.locator('.q-table').first()).toContainText(name)
  }
  await glyphs.getByRole('combobox', { name: 'Glyphes et illustrations', exact: true }).click()
  await page.getByRole('option', { name: 'Material utilisés', exact: true }).click()
  await glyphs.getByLabel('Rechercher', { exact: true }).fill('search')
  await expect(glyphs.getByRole('cell', { name: 'search', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Thème sombre', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Thème clair', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('reference-desktop-dark.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: testInfo.outputPath('reference-mobile-dark.png'), fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Réinitialiser', exact: true }).click()
  await expect(glyphs.getByLabel('Rechercher', { exact: true })).toHaveValue('')
})
