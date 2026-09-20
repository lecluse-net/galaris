import { test, expect, mount } from './fixtures.mjs'

for (const locale of ['en', 'fr']) test(`confirmations cancel safely, reopen and confirm once (${locale})`, async ({ page }, testInfo) => {
  await mount(page, 'core/util/components/FolderIcon.vue', { locale })
  const open = async options => page.evaluate(async options => {
    const { showConfirmationDialog } = await import('/core/util/confirmationDialog.ts')
    window.dialogOutcomes ??= []
    showConfirmationDialog({
      title: 'A confirmation with an existing resource', message: 'Keep this content\nSecond line',
      cancel: true, ok: { label: 'Proceed', color: 'negative' }, focus: 'cancel', ...options,
    }).onOk(() => window.dialogOutcomes.push('ok'))
      .onCancel(() => window.dialogOutcomes.push('cancel'))
      .onDismiss(() => window.dialogOutcomes.push('dismiss'))
  }, options)
  const dialog = page.getByRole('dialog')
  const close = () => dialog.getByRole('button', { name: locale === 'fr' ? 'Fermer' : 'Close', exact: true })
  const cancel = () => dialog.getByRole('button', { name: locale === 'fr' ? 'Annuler' : 'Cancel', exact: true })
  await open()
  await expect(dialog).toContainText('Keep this content')
  await expect(cancel()).toBeFocused()
  await close().click()
  await expect(dialog).toHaveCount(0)
  await open()
  await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(dialog).toHaveCount(0)
  await open()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await open()
  await cancel().click()
  await expect(dialog).toHaveCount(0)
  expect(await page.evaluate(() => window.dialogOutcomes)).toEqual(Array(4).fill(['cancel', 'dismiss']).flat())

  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.testApp.dark(true))
  await open({ title: 'A long resource title '.repeat(8) })
  await expect(close()).toBeInViewport()
  await expect(dialog.getByRole('button', { name: 'Proceed', exact: true })).toBeInViewport()
  await page.screenshot({ animations: 'disabled', path: testInfo.outputPath('confirmation-mobile-dark.png') })
  await dialog.getByRole('button', { name: 'Proceed', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(await page.evaluate(() => window.dialogOutcomes.slice(-2))).toEqual(['ok', 'dismiss'])
})

test('detail headers keep long titles readable and can close and reopen', async ({ page }, testInfo) => {
  await mount(page, 'core/util/components/ConversationTurnDialog.vue', {
    props: { modelValue: true, title: 'An existing conversation '.repeat(8), closeLabel: 'Close', icon: 'chat' },
  })
  const dialog = page.getByRole('dialog')
  for (const [width, dark] of [[1440, false], [390, true]]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.evaluate(dark => window.testApp.dark(dark), dark)
    await expect(dialog).toContainText('An existing conversation')
    await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeInViewport()
    await page.screenshot({ animations: 'disabled', path: testInfo.outputPath(`detail-${width}.png`) })
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await page.evaluate(() => window.testApp.setProps({ modelValue: true }))
  }
})
