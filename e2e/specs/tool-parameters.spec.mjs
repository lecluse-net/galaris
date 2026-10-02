import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'
import { selectOption } from '../select-option.mjs'

for (const mobile of [false, true]) {
  test(`Tool parameter labels and choices persist across editing and global settings (${mobile ? 'mobile' : 'desktop'})`, async ({ page, request }, testInfo) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 })
    const pageErrors = collectPageErrors(page)
    const fixture = await (await request.post('/api/__test/seed')).json()
    const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
    await page.goto('/user/login')
    await refresh
    await page.locator('input[type=email]').fill(fixture.email)
    await page.locator('input[type=password]').fill(fixture.password)
    const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
    await page.locator('button[type=submit]').click()
    const session = await (await login).json()
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    const headers = { Authorization: `Bearer ${session.access_token}` }
    const errors = []
    page.on('response', response => {
      const path = new URL(response.url()).pathname
      if (path.startsWith('/api/') && response.status() >= 400) errors.push(`${response.status()} ${path}`)
    })
    await pageErrors.settle()
    await page.goto('/tools')
    if (!mobile) {
      const catalog = await (await request.get('/api/tools', { headers })).json()
      const internal = catalog.filter(entry => Object.values(entry.connection_schema?.params ?? {})
        .some(parameter => parameter.label?.startsWith('tools.connectionParamLabels.')))
      expect(internal.map(entry => entry.code)).toEqual(expect.arrayContaining(['browser', 'console', 'mail', 'calendar']))
      // Check the real backend definitions against each catalogue, without a fallback language hiding missing keys.
      const untranslated = await page.evaluate(entries => {
        const { $te } = document.querySelector('#app').__vue_app__.config.globalProperties
        const failures = []
        for (const locale of ['fr', 'en', 'zh']) {
          for (const entry of entries) {
            for (const [name, parameter] of Object.entries(entry.connection_schema.params)) {
              for (const definition of [parameter, ...(parameter.options ?? [])]) {
                if (definition.label?.startsWith('tools.') && !$te(definition.label, locale)) {
                  failures.push(`${locale}:${entry.code}:${name}:${definition.label}`)
                }
              }
            }
          }
        }
        return failures
      }, internal)
      expect(untranslated).toEqual([])
    }
    if (mobile) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop => backdrop.click({ position: { x: 380, y: 150 } }), { times: 1 })
    await page.getByRole('button', { name: 'Nouvel outil', exact: true }).click()
    const editor = page.getByRole('dialog')
    const code = `synthetic-params-${fixture.agent_id}`
    await editor.getByLabel('Nom technique *', { exact: true }).fill(code)
    await editor.getByLabel('Libellé *', { exact: true }).fill(`Synthetic parameter choices ${fixture.agent_id}`)
    await editor.getByRole('button', { name: 'Ajouter un param', exact: true }).click()
    await editor.getByLabel('Nom *', { exact: true }).fill('region')
    await editor.getByLabel('Libellé du paramètre', { exact: true }).fill('Région du service')
    await editor.getByLabel('Valeur par défaut', { exact: true }).fill('eu')
    for (const [value, label] of [['eu', 'Europe'], ['us', 'Amérique du Nord']]) {
      await editor.getByRole('button', { name: 'Ajouter un choix fixe', exact: true }).click()
      await editor.getByLabel('Valeur *', { exact: true }).last().fill(value)
      await editor.getByLabel('Libellé du choix', { exact: true }).last().fill(label)
    }
    const create = page.waitForResponse(response => response.url().endsWith('/api/tools') && response.request().method() === 'POST')
    await editor.getByRole('button', { name: 'Créer', exact: true }).click()
    const response = await create
    expect(response.ok(), await response.text()).toBe(true)
    const created = await response.json()
    await expect(editor).toHaveCount(0)
    await pageErrors.settle()
    await page.reload()
    if (mobile) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop => backdrop.click({ position: { x: 380, y: 150 } }), { times: 1 })
    const row = page.locator(mobile ? '.tool-mobile-card' : 'tbody tr').filter({ hasText: code })
    await row.getByRole('button', { name: "Modifier l'outil", exact: true }).click()
    await expect(editor.getByLabel('Libellé du paramètre', { exact: true })).toHaveValue('Région du service')
    await expect(editor.getByLabel('Libellé du choix', { exact: true }).last()).toHaveValue('Amérique du Nord')
    await editor.getByRole('button', { name: 'Fermer', exact: true }).click()
    await row.getByRole('button', { name: 'Paramètres globaux', exact: true }).click()
    await selectOption(page, editor.getByRole('combobox', { name: 'Région du service *', exact: true }), 'Amérique du Nord')
    await page.screenshot({ path: testInfo.outputPath('global-parameters.png'), animations: 'disabled' })
    const saved = page.waitForResponse(response => response.url().endsWith(`/api/tools/${created.id}/global-params`)
      && response.request().method() === 'PUT')
    await editor.getByRole('button', { name: 'Enregistrer', exact: true }).click()
    expect((await saved).ok()).toBe(true)
    await expect(editor).toHaveCount(0)
    const globals = await (await request.get(`/api/tools/${created.id}/global-params`, { headers })).json()
    expect(globals.params.region.value).toBe('us')
    await row.getByRole('button', { name: 'Paramètres globaux', exact: true }).click()
    await expect(editor.getByRole('combobox', { name: 'Région du service *', exact: true })).toHaveValue('Amérique du Nord')
    await editor.getByRole('button', { name: 'Fermer', exact: true }).click()
    // A file provider supplies tools.fileindexing through the same global/local parameter journey.
    const updated = await request.put(`/api/tools/${created.id}`, { headers, data: {
      file_share_config: { service: 'nextcloud', base_url: 'https://synthetic.invalid', param_map: {} },
    } })
    expect(updated.ok(), await updated.text()).toBe(true)
    const definition = (await updated.json()).connection_schema.params['tools.fileindexing']
    expect(definition.options.map(option => option.value)).toEqual(['excluded', 'known_uris', 'recursive'])
    await pageErrors.settle()
    await page.reload()
    if (mobile) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop => backdrop.click({ position: { x: 380, y: 150 } }), { times: 1 })
    await row.getByRole('button', { name: 'Paramètres globaux', exact: true }).click()
    await selectOption(page, editor.getByRole('combobox', { name: 'Indexation des fichiers', exact: true }), 'Uniquement les fichiers déjà connus')
    const savedIndexing = page.waitForResponse(response => response.url().endsWith(`/api/tools/${created.id}/global-params`) && response.request().method() === 'PUT')
    await editor.getByRole('button', { name: 'Enregistrer', exact: true }).click()
    expect((await savedIndexing).ok()).toBe(true)
    await expect(editor).toHaveCount(0)
    const indexingGlobals = await (await request.get(`/api/tools/${created.id}/global-params`, { headers })).json()
    expect(indexingGlobals.params['tools.fileindexing'].value).toBe('known_uris')
    const connectionResponse = await request.post('/api/connections', { headers, data: { tool_id: created.id, agent_id: fixture.agent_id, active: false } })
    expect(connectionResponse.ok(), await connectionResponse.text()).toBe(true)
    const connection = await connectionResponse.json()
    await pageErrors.settle()
    await page.goto('/tools?tab=connections')
    if (mobile) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop => backdrop.click({ position: { x: 380, y: 150 } }), { times: 1 })
    const agent = await (await request.get(`/api/agents/${fixture.agent_id}`, { headers })).json()
    await selectOption(page, page.getByRole('combobox', { name: 'Filtrer par agent', exact: true }), `${agent.first_name} ${agent.last_name}`)
    await page.getByRole('button', { name: 'Inactives', exact: true }).click()
    const connectionRow = page.locator(mobile ? '.connection-mobile-card' : 'tbody tr').filter({ hasText: created.label })
    await connectionRow.getByRole('button', { name: 'Modifier', exact: true }).click()
    await editor.getByText('Paramètres globaux hérités (2)', { exact: true }).click()
    const inheritedIndexing = editor.locator('.q-item').filter({ hasText: 'Indexation des fichiers' })
    await expect(inheritedIndexing).toContainText('Uniquement les fichiers déjà connus')
    await inheritedIndexing.getByRole('button', { name: 'Personnaliser', exact: true }).click()
    await selectOption(page, editor.getByRole('combobox', { name: 'Indexation des fichiers', exact: true }), 'Désactivée')
    const savedLocal = page.waitForResponse(response => response.url().endsWith(`/api/connections/${connection.id}/params/bulk`) && response.request().method() === 'POST')
    await editor.getByRole('button', { name: 'Modifier', exact: true }).click()
    expect((await savedLocal).ok()).toBe(true)
    await expect(editor).toHaveCount(0)
    const local = await (await request.get(`/api/connections/${connection.id}/params`, { headers })).json()
    expect(local.params['tools.fileindexing']).toBe('excluded')
    const inheritedGlobal = await (await request.get(`/api/tools/${created.id}/global-params`, { headers })).json()
    expect(inheritedGlobal.params['tools.fileindexing'].value).toBe('known_uris')
    await connectionRow.getByRole('button', { name: 'Modifier', exact: true }).click()
    await expect(editor).toBeVisible()
    await expect(editor.getByRole('combobox', { name: 'Indexation des fichiers', exact: true })).toBeVisible()
    await expect(editor.getByRole('combobox', { name: 'Indexation des fichiers', exact: true })).toHaveValue('Désactivée')
    await page.screenshot({ path: testInfo.outputPath('connection-file-indexing.png'), animations: 'disabled' })
    await editor.getByRole('button', { name: 'Fermer', exact: true }).click()
    expect((await request.delete(`/api/connections/${connection.id}`, { headers })).ok()).toBe(true)
    expect((await request.delete(`/api/tools/${created.id}`, { headers })).ok()).toBe(true)
    expect([...errors, ...pageErrors()]).toEqual([])
  })
}
