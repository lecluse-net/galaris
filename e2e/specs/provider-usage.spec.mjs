import { test, expect } from '@playwright/test'

test('provider credits open, refresh, recover and reopen in the assembled application', async ({ page, request }, testInfo) => {
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok()).toBeTruthy()
  const fixture = await seeded.json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('.user-menu-wrapper').first()).toBeVisible()
  // The installation ships an unconfigured OpenRouter connection. Keep the
  // journey on the synthetic service rather than trying its external catalog.
  expect((await request.put('/api/llm-providers/catalog/openrouter', {
    headers: { Authorization: `Bearer ${session.access_token}` }, data: { is_active: false },
  })).ok()).toBeTruthy()
  const configured = await request.put('/api/llm-providers/catalog/elevenlabs', {
    headers: { Authorization: `Bearer ${session.access_token}` },
    data: { api_key: 'synthetic-e2e-quota-key', is_active: true },
  })
  expect(configured.ok(), await configured.text()).toBeTruthy()
  const failures = []
  page.on('pageerror', error => failures.push(error.message))
  page.on('response', response => {
    if (new URL(response.url()).pathname.startsWith('/api/') && response.status() >= 400
        && !response.url().endsWith('/quota')) failures.push(`${response.status()} ${response.url()}`)
  })
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    expect((await request.put('/api/__test/provider-usage?used=2500&status=200')).ok()).toBeTruthy()
    await page.goto('/llm?tab=providers')
    if (width < 1024) {
      await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), async backdrop => {
        await backdrop.click({ position: { x: width - 10, y: 200 } })
      }, { times: 1 })
    }
    await page.locator('.provider-list-panel').getByText('ElevenLabs', { exact: true }).click()
    const panel = page.locator('.provider-config-panel')
    await expect(panel.getByText('25 % utilisés', { exact: true })).toBeVisible()
    await expect(panel.getByText(/^Restants :.*7.*500.*crédits$/)).toBeVisible()
    await expect(panel.getByText(/^Réinitialisation :/)).toBeVisible()
    await panel.screenshot({ path: testInfo.outputPath(`provider-credits-${width}.png`) })
    expect((await request.put('/api/__test/provider-usage?used=10000&status=200')).ok()).toBeTruthy()
    const reload = panel.getByRole('button', { name: 'Actualiser les limites' })
    await reload.focus()
    await page.keyboard.press('Enter')
    await expect(panel.getByText('100 % utilisés', { exact: true })).toBeVisible()
    await expect(panel.getByText('Restants : 0 crédits', { exact: true })).toBeVisible()
    expect((await request.put('/api/__test/provider-usage?used=10000&status=503')).ok()).toBeTruthy()
    await reload.click()
    await expect(panel.getByRole('alert').filter({ hasText: 'Limites indisponibles' })).toBeVisible()
    expect((await request.put('/api/__test/provider-usage?used=5000&status=200')).ok()).toBeTruthy()
    await reload.click()
    await expect(panel.getByText('50 % utilisés', { exact: true })).toBeVisible()
    await page.locator('.provider-list-panel').getByText('DeepSeek', { exact: true }).click()
    await expect(panel.getByText('Consommation et crédits', { exact: true })).toHaveCount(0)
    await page.locator('.provider-list-panel').getByText('ElevenLabs', { exact: true }).click()
    await expect(panel.getByText('50 % utilisés', { exact: true })).toBeVisible()
  }
  expect((await request.put('/api/llm-providers/catalog/openrouter', {
    headers: { Authorization: `Bearer ${session.access_token}` },
    data: { api_key: 'synthetic-e2e-inference-key', is_active: true },
  })).ok()).toBeTruthy()
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    expect((await request.put('/api/__test/provider-usage?status=200')).ok()).toBeTruthy()
    await page.goto('/llm?tab=providers')
    if (width < 1024) {
      await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), async backdrop => {
        await backdrop.click({ position: { x: width - 10, y: 200 } })
      }, { times: 1 })
    }
    await page.locator('.provider-list-panel').getByText('OpenRouter', { exact: true }).click()
    const panel = page.locator('.provider-config-panel')
    const key = panel.getByLabel('Clé de gestion (facultative)', { exact: true })
    const inferenceKey = panel.getByLabel('Jeton / clé API', { exact: true })
    await expect(inferenceKey).toHaveValue('')
    await expect(inferenceKey).toHaveAttribute('type', 'password')
    await expect(inferenceKey).toHaveAttribute('placeholder', '**********')
    await expect(panel.getByText('Jeton / clé API', { exact: true })).toBeVisible()
    await expect(key).toHaveValue('')
    await expect(key).toHaveAttribute('type', 'password')
    await expect(panel.getByText(/^Restants : 6,00\s+USD$/)).toBeVisible()
    await expect(panel.getByRole('progressbar')).toHaveCount(0)
    await expect(panel.getByText(/^Plafond :|^Consommés :|% utilisés$/)).toHaveCount(0)
    await expect(panel.getByRole('link', { name: 'Créer une clé de gestion OpenRouter' }))
      .toHaveAttribute('href', 'https://openrouter.ai/settings/management-keys')
    const saved = page.waitForResponse(response => response.url().endsWith('/api/llm-providers/catalog/openrouter')
      && response.request().method() === 'PUT')
    await key.fill('synthetic-e2e-management-key')
    const response = await saved
    expect(response.ok()).toBeTruthy()
    expect(await response.text()).not.toContain('synthetic-e2e-management-key')
    await expect(panel.getByText(/^Restants : 75,00\s+USD$/)).toBeVisible()
    await expect(panel.getByRole('progressbar')).toHaveCount(0)
    await expect(panel.getByText(/^Plafond :|^Consommés :|% utilisés$/)).toHaveCount(0)
    await expect(panel.getByText('Consommation du compte connecté, tous clients confondus.')).toBeVisible()
    await page.locator('.provider-list-panel').getByText('DeepSeek', { exact: true }).click()
    await page.locator('.provider-list-panel').getByText('OpenRouter', { exact: true }).click()
    await expect(key).toHaveValue('')
    await expect(panel.getByText(/Une clé de gestion est enregistrée et chiffrée/)).toBeVisible()
    await expect(key).toHaveAttribute('placeholder', '**********')
    await expect(panel.getByText('Clé de gestion (facultative)', { exact: true })).toBeVisible()
    await expect(panel.getByText(/^Restants : 75,00\s+USD$/)).toBeVisible()
    await expect(panel.getByRole('progressbar')).toHaveCount(0)
    await panel.screenshot({ path: testInfo.outputPath(`openrouter-management-${width}.png`) })
    expect((await request.put('/api/__test/provider-usage?status=503')).ok()).toBeTruthy()
    const reload = panel.getByRole('button', { name: 'Actualiser les limites' })
    await reload.focus()
    await page.keyboard.press('Enter')
    await expect(panel.getByRole('alert').filter({ hasText: 'Limites indisponibles' })).toBeVisible()
    expect((await request.put('/api/__test/provider-usage?status=200')).ok()).toBeTruthy()
    await reload.click()
    await expect(panel.getByText(/^Restants : 75,00\s+USD$/)).toBeVisible()
    await panel.getByRole('button', { name: 'Supprimer la clé de gestion', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Supprimer', exact: true }).click()
    await expect(panel.getByText(/^Restants : 6,00\s+USD$/)).toBeVisible()
    await expect(panel.getByRole('progressbar')).toHaveCount(0)
    await expect(panel.getByText(/Consommation et plafond de la clé API configurée/)).toBeVisible()
    await panel.getByRole('button', { name: 'Supprimer la clé API', exact: true }).click()
    const removal = page.waitForResponse(response => response.url().endsWith('/api/llm-providers/catalog/openrouter')
      && response.request().method() === 'PUT')
    await page.getByRole('dialog').getByRole('button', { name: 'Supprimer', exact: true }).click()
    const removed = await removal
    expect(removed.ok()).toBeTruthy()
    expect((await removed.json()).api_key_configured).toBe(false)
    await expect(panel.getByRole('switch')).not.toBeChecked()
    await expect(panel.getByRole('button', { name: 'Supprimer la clé API', exact: true })).toHaveCount(0)
    await expect(inferenceKey).toHaveValue('')
    // Restore the synthetic inference connection for the next viewport.
    await inferenceKey.fill('synthetic-e2e-inference-key')
    await panel.getByRole('button', { name: 'Enregistrer', exact: true }).click()
    await panel.getByRole('switch').click()
    await expect(panel.getByText(/^Restants : 6,00\s+USD$/)).toBeVisible()
  }
  expect((await request.put('/api/llm-providers/catalog/fireworks', {
    headers: { Authorization: `Bearer ${session.access_token}` },
    data: { api_key: 'synthetic-e2e-fireworks-key', is_active: false, configuration: {} },
  })).ok()).toBeTruthy()
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    expect((await request.put('/api/__test/provider-usage?used=2500')).ok()).toBeTruthy()
    await page.goto('/llm?tab=providers')
    if (width < 1024) {
      await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), async backdrop => {
        await backdrop.click({ position: { x: width - 10, y: 200 } })
      }, { times: 1 })
    }
    await page.locator('.provider-list-panel').getByText('Fireworks AI', { exact: true }).click()
    const panel = page.locator('.provider-config-panel')
    const key = panel.getByLabel('Jeton / clé API', { exact: true })
    await expect(key).toBeVisible()
    await key.focus()
    await expect(key).toBeFocused()
    await expect(panel.getByText('Solde disponible', { exact: true })).toHaveCount(0)
    await expect(panel.getByRole('link', { name: 'Voir mon solde Fireworks' })).toHaveCount(0)
    await expect(panel.getByRole('progressbar')).toHaveCount(0)
    await expect(panel.getByText(/^Restants :/)).toHaveCount(0)
    await page.locator('.provider-list-panel').getByText('DeepSeek', { exact: true }).click()
    await page.locator('.provider-list-panel').getByText('Fireworks AI', { exact: true }).click()
    await expect(key).toBeVisible()
    await expect(panel.getByText('Solde disponible', { exact: true })).toHaveCount(0)
    await expect(panel.getByRole('progressbar')).toHaveCount(0)
    await expect(panel.getByText(/^Restants :/)).toHaveCount(0)
    await panel.screenshot({ path: testInfo.outputPath(`fireworks-config-${width}.png`) })
  }
  expect(failures).toEqual([])
})

test('ChatGPT additional credits remain distinct from subscription windows', async ({ page, request }, testInfo) => {
  await page.clock.install()
  const seeded = await request.post('/api/__test/seed')
  expect(seeded.ok()).toBeTruthy()
  const fixture = await seeded.json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  const headers = { Authorization: `Bearer ${session.access_token}` }
  await expect(page.locator('.user-menu-wrapper').first()).toBeVisible()
  const owner = await request.get('/api/auth/me', { headers })
  expect(owner.ok()).toBeTruthy()
  const configured = await request.put('/api/llm-providers/catalog/openai-codex', {
    headers, data: { is_active: false, subscription_acknowledged: true, user_id: (await owner.json()).id },
  })
  expect(configured.ok(), await configured.text()).toBeTruthy()
  expect((await request.post(`/api/__test/codex-credits/${(await configured.json()).id}`)).ok()).toBeTruthy()
  const failures = []
  page.on('pageerror', error => failures.push(error.message))
  page.on('response', response => {
    if (new URL(response.url()).pathname.startsWith('/api/') && response.status() >= 400
        && !response.url().endsWith('/quota')) failures.push(`${response.status()} ${response.url()}`)
  })
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    expect((await request.put('/api/__test/provider-usage?codex_credits=125.5')).ok()).toBeTruthy()
    await page.goto('/llm?tab=providers')
    if (width < 1024) {
      await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), async backdrop => {
        await backdrop.click({ position: { x: width - 10, y: 200 } })
      }, { times: 1 })
    }
    await page.locator('.provider-list-panel').getByText('OpenAI — ChatGPT', { exact: true }).click()
    const panel = page.locator('.provider-config-panel')
    await expect(panel.getByText('37 % utilisés', { exact: true })).toBeVisible()
    await expect(panel.getByText('0 % utilisés', { exact: true })).toBeVisible()
    await expect(panel.getByText('Restants : 125,5 crédits', { exact: true })).toBeVisible()
    await expect(panel.getByRole('progressbar')).toHaveCount(2)
    await expect(panel.getByText(/^Plafond :|^Consommés :/)).toHaveCount(0)
    await panel.screenshot({ path: testInfo.outputPath(`chatgpt-credits-${width}.png`) })
    expect((await request.put('/api/__test/provider-usage?codex_credits=0')).ok()).toBeTruthy()
    const reload = panel.getByRole('button', { name: 'Actualiser les limites' })
    await reload.focus()
    await page.keyboard.press('Enter')
    await expect(panel.getByText('Restants : 0 crédits', { exact: true })).toBeVisible()
    expect((await request.put('/api/__test/provider-usage?status=503')).ok()).toBeTruthy()
    await reload.click()
    await expect(panel.getByRole('alert').filter({ hasText: 'Limites indisponibles' })).toBeVisible()
    await expect(panel.getByText(/^Restants :/)).toHaveCount(0)
    expect((await request.put('/api/__test/provider-usage?codex_credits=75')).ok()).toBeTruthy()
    await reload.click()
    await expect(panel.getByText('Restants : 75 crédits', { exact: true })).toBeVisible()
    await page.locator('.provider-list-panel').getByText('DeepSeek', { exact: true }).click()
    await page.locator('.provider-list-panel').getByText('OpenAI — ChatGPT', { exact: true }).click()
    await expect(panel.getByText('Restants : 75 crédits', { exact: true })).toBeVisible()
    await expect(panel.getByRole('progressbar')).toHaveCount(2)
    let quotaReads = 0
    const countQuotaReads = outgoing => {
      if (outgoing.url().endsWith('/quota')) quotaReads += 1
    }
    page.on('request', countQuotaReads)
    expect((await request.put('/api/__test/provider-usage?codex_credits=50')).ok()).toBeTruthy()
    await page.clock.fastForward('05:00')
    await expect(panel.getByText('Restants : 50 crédits', { exact: true })).toBeVisible()
    expect(quotaReads).toBe(1)
    await page.getByRole('tab', { name: 'Modèles disponibles', exact: true }).click()
    await expect(panel).toBeHidden()
    await page.clock.fastForward('05:00')
    expect(quotaReads).toBe(1)
    await page.getByRole('tab', { name: 'Fournisseurs', exact: true }).click()
    await expect(panel).toBeVisible()
    expect((await request.put('/api/__test/provider-usage?codex_credits=25')).ok()).toBeTruthy()
    await page.clock.fastForward('05:00')
    await expect(panel.getByText('Restants : 25 crédits', { exact: true })).toBeVisible()
    expect(quotaReads).toBe(2)
    page.off('request', countQuotaReads)
  }
  expect(failures).toEqual([])
})
