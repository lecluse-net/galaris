import { test, expect, mount } from './fixtures.mjs'

const manifest = {
  code: 'example.studio', version: '1.0.0',
  label: { fr: 'Studio de test', en: 'Synthetic studio' },
  description: { fr: 'Exemple de plugin déclaratif.', en: 'A synthetic declarative plugin.' },
  minimum_galaris_version: '0.1.0', maximum_galaris_version_exclusive: '0.3.0',
  contributions: [
    { family: 'service_preset', code: 'first-test', label: { fr: 'Premier Service', en: 'First Service' }, contract_version: 1 },
    { family: 'service_preset', code: 'second-test', label: { fr: 'Second Service', en: 'Second Service' }, contract_version: 1 },
  ],
}
const preview = {
  manifest, digest: 'a'.repeat(64), signer: 'b'.repeat(64), host_identity: 'c'.repeat(64),
  host_version: '0.2.0', can_force: false, compatibility: 'supported',
}

test('inspect an archive, install it inactive and manage its release after reopening', async ({ page }, testInfo) => {
  let release = null
  let previewAttempts = 0
  let rejectActivation = false
  const previous = {
    ...preview, manifest: { ...manifest, version: '0.9.0' },
    installed: false, active: false, selected: false, forced: false,
  }
  await page.route('**/api/plugins', route => route.fulfill({ json: release ? [release] : [] }))
  await page.route('**/api/plugins/preview', route => {
    previewAttempts++
    return previewAttempts === 1
      ? route.fulfill({ status: 422, json: { detail: 'invalid_signature' } })
      : route.fulfill({ json: preview })
  })
  await page.route('**/api/plugins/install', route => {
    release = { ...preview, installed: true, active: false, selected: false, forced: false }
    return route.fulfill({ json: release })
  })
  await page.route('**/api/plugins/example.studio', route => route.fulfill({
    json: { code: manifest.code, releases: [release, previous], events: [
      { version: manifest.version, operation: 'installed', occurred_at: '2026-11-18T12:00:00Z', forced: false },
    ] },
  }))
  await page.route('**/api/plugins/example.studio/1.0.0/*', route => {
    const action = new URL(route.request().url()).pathname.split('/').at(-1)
    if (action === 'activate' && rejectActivation) {
      rejectActivation = false
      return route.fulfill({ status: 409, json: { detail: 'activation_error' } })
    }
    const active = action === 'activate'
    release = { ...release, active, selected: active, installed: action !== 'remove' }
    return route.fulfill({ json: release })
  })

  const options = { locale: 'fr', route: '/plugin', shell: true, privileges: ['PLUGIN_EDIT'] }
  await mount(page, 'app/plugin/pages/index.vue', options)
  await expect(page.getByText('Aucun plugin installé.')).toBeVisible()
  await page.getByRole('button', { name: 'Importer un plugin' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.locator('input[type=file]').setInputFiles({
    name: 'synthetic.zip', mimeType: 'application/zip', buffer: Buffer.from('synthetic transport fixture'),
  })
  await expect(dialog.getByRole('alert')).toContainText('La signature ou une empreinte est invalide.')
  await expect(dialog.getByRole('button', { name: 'Installer', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: 'Réessayer', exact: true }).click()
  await expect(dialog.getByText('Premier Service', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Second Service', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('checkbox', { name: /Forcer/ })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Installer', exact: true }).click()
  await expect(dialog).toHaveCount(0)

  const studio = page.getByRole('article', { name: 'Studio de test' })
  await expect(studio.getByText('Premier Service', { exact: true })).toBeVisible()
  await expect(studio.getByText('Inactif', { exact: true })).toBeVisible()
  const activation = studio.getByRole('switch', { name: 'Activation de Studio de test' })
  await expect(activation).toHaveAttribute('aria-checked', 'false')
  await activation.click()
  await expect(studio.getByText('Actif', { exact: true })).toBeVisible()
  await expect(activation).toHaveAttribute('aria-checked', 'true')
  await activation.click()
  await expect(studio.getByText('Inactif', { exact: true })).toBeVisible()
  const activationError = page.getByText('Le chargement du plugin a échoué. La sélection précédente est conservée.')
  rejectActivation = true
  await activation.press('Space')
  await expect(activationError).toBeVisible()
  await expect(studio.getByText('Inactif', { exact: true })).toBeVisible()
  await expect(activation).toHaveAttribute('aria-checked', 'false')
  await activation.click()
  await expect(studio.getByText('Actif', { exact: true })).toBeVisible()
  await expect(activationError).toBeHidden()
  await page.screenshot({ path: testInfo.outputPath('plugin-desktop.png'), animations: 'disabled' })

  await page.setViewportSize({ width: 390, height: 844 })
  await mount(page, 'app/plugin/pages/index.vue', { ...options, dark: true })
  await page.locator('.q-drawer__backdrop').click({ position: { x: 380, y: 200 } })
  await expect(activation).toHaveAttribute('aria-checked', 'true')
  await activation.click()
  await expect(activation).toHaveAttribute('aria-checked', 'false')
  await expect(activation).toBeEnabled()
  await studio.screenshot({ path: testInfo.outputPath('plugin-mobile.png'), animations: 'disabled' })
  const history = studio.getByRole('button', { name: 'Versions et historique' })
  await history.press('Enter')
  await expect(studio.getByText('Version 1.0.0 installée')).toBeVisible()
  const version = studio.getByRole('combobox', { name: 'Version', exact: true })
  await version.click()
  await page.getByRole('option', { name: /0\.9\.0/ }).click()
  await expect(studio.getByText('example.studio · 0.9.0')).toBeVisible()
  await version.click()
  await page.getByRole('option', { name: /1\.0\.0/ }).click()
  await expect(studio.getByText('Inactif', { exact: true })).toBeVisible()
  const uninstall = studio.getByRole('button', { name: 'Désinstaller', exact: true })
  await uninstall.click()
  await expect(dialog).toContainText('Les Services déjà créés seront conservés.')
  await expect(dialog.getByRole('button', { name: 'Désinstaller', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(studio.getByText('Inactif', { exact: true })).toBeVisible()
  await uninstall.click()
  await expect(dialog.getByRole('button', { name: 'Désinstaller', exact: true })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(studio.getByText('Désinstallé', { exact: true })).toBeVisible()
  await expect(dialog).toHaveCount(0)
  await expect(activation).toHaveCount(0)
})

test('development samples show their manifest and can be activated from Plugins', async ({ page }, testInfo) => {
  let rest = {
    source: 'development_sample', active: true, target: 'rest',
    endpoint: 'http://127.0.0.1:8000/api/plugin-samples/rest',
    manifest: { ...manifest, code: 'sample.rest', label: { en: 'Sample REST', fr: 'Sample REST' } },
  }
  const drawing = {
    source: 'development_sample', active: true, target: 'documents', endpoint: null,
    manifest: {
      ...manifest, code: 'sample.drawing', label: { en: 'Drawing (Sample)', fr: 'Dessin (Sample)' },
      contributions: [{ ...manifest.contributions[0], family: 'document_format', code: 'sample.drawing' }],
    },
  }
  await page.route('**/api/plugins', route => route.fulfill({ json: [rest, drawing] }))
  await page.route('**/api/plugins/sample.rest/1.0.0/*', route => {
    expect(route.request().postDataJSON()).toEqual({ source: 'development_sample' })
    rest = { ...rest, active: new URL(route.request().url()).pathname.endsWith('/activate') }
    return route.fulfill({ json: rest })
  })
  await mount(page, 'app/plugin/pages/index.vue', {
    locale: 'fr', route: '/plugin', shell: true, privileges: ['PLUGIN_EDIT'],
  })
  const serviceCard = page.getByRole('article', { name: 'Sample REST' })
  const drawingCard = page.getByRole('article', { name: 'Dessin (Sample)' })
  await expect(serviceCard.getByText(rest.manifest.description.fr, { exact: true })).toBeVisible()
  await expect(drawingCard.getByText('Format de document', { exact: false })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('plugin-samples-grid.png'), animations: 'disabled' })
  const activation = serviceCard.getByRole('switch', { name: 'Activation de Sample REST' })
  await expect(activation).toHaveAttribute('aria-checked', 'true')
  await activation.click()
  await expect(activation).toHaveAttribute('aria-checked', 'false')
  await expect(serviceCard.getByText('Inactif', { exact: true })).toBeVisible()
  await activation.click()
  await expect(activation).toHaveAttribute('aria-checked', 'true')
  await expect(serviceCard.getByText('Actif', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('a catalogue release goes through the same signed preview before installation', async ({ page }) => {
  await page.route('**/api/plugins', route => route.fulfill({ json: [] }))
  await page.route('**/api/plugins/catalog', route => route.fulfill({ json: [preview] }))
  await page.route(`**/api/plugins/catalog/${preview.digest}`, route => route.fulfill({
    contentType: 'application/zip', body: 'Synthetic signed archive transport fixture',
  }))
  let inspected = false
  await page.route('**/api/plugins/preview', route => {
    inspected = route.request().postData()?.includes('Synthetic signed archive transport fixture') ?? false
    return route.fulfill({ json: preview })
  })
  await mount(page, 'app/plugin/pages/index.vue', { locale: 'fr', route: '/plugin', privileges: ['PLUGIN_EDIT'] })
  await page.getByRole('button', { name: 'Catalogue', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Version à installer' }).click()
  await page.getByRole('option', { name: /Studio de test.*1\.0\.0/ }).click()
  await expect(dialog.getByText('Premier Service', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Installer', exact: true })).toBeEnabled()
  expect(inspected).toBe(true)
})
