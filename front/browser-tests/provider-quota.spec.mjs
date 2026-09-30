import { test, expect, mount } from './fixtures.mjs'

const snapshot = (percent = 37, credits = 125.5) => ({
  windows: [
    { name: 'primary', used_percent: percent, window_seconds: 18000, resets_at: '2033-05-18T03:33:20Z' },
    { name: 'secondary', used_percent: 0, window_seconds: 604800, resets_at: null },
    { name: 'credits', remaining: credits, unit: 'credits', used_percent: null },
  ],
  checked_at: '2033-05-18T02:00:00Z',
})

test('account windows load, refresh, and recover from unavailable quotas', async ({ page }) => {
  let response = snapshot()
  let status = 200
  await page.route('**/api/llm-providers/17/quota', route => route.fulfill({ status, json: response }))
  await mount(page, 'app/llm/components/ProviderQuotaPanel.vue', { props: { providerId: 17 } })
  await expect(page.getByText('37% used', { exact: true })).toBeVisible()
  await expect(page.getByText('0% used', { exact: true })).toBeVisible()
  await expect(page.getByText('Over 5 h', { exact: true })).toBeVisible()
  await expect(page.getByText('Over 7 d', { exact: true })).toBeVisible()
  await expect(page.getByText(/^Resets:/)).toBeVisible()
  await expect(page.getByText('Remaining: 125.5 credits', { exact: true })).toBeVisible()
  await expect(page.getByRole('progressbar')).toHaveCount(2)
  response = snapshot(100, 0)
  await page.getByRole('button', { name: 'Refresh limits' }).click()
  await expect(page.getByText('100% used', { exact: true })).toBeVisible()
  await expect(page.getByText('Remaining: 0 credits', { exact: true })).toBeVisible()
  status = 502
  await page.getByRole('button', { name: 'Refresh limits' }).click()
  await expect(page.getByRole('alert')).toContainText('Limits unavailable')
  await expect(page.getByText('100% used', { exact: true })).toHaveCount(0)
  await expect(page.getByText(/^Remaining:/)).toHaveCount(0)
  status = 200
  response = { windows: [], checked_at: snapshot().checked_at }
  await page.getByRole('button', { name: 'Refresh limits' }).click()
  await expect(page.getByText('The provider did not report any usage or limits.')).toBeVisible()
  response = snapshot(21)
  await mount(page, 'app/llm/components/ProviderQuotaPanel.vue', { props: { providerId: 17 } })
  await expect(page.getByText('21% used', { exact: true })).toBeVisible()
  await expect(page.getByText('Remaining: 125.5 credits', { exact: true })).toBeVisible()
})

for (const width of [1440, 390]) {
  test(`Fireworks configuration has no balance panel or spend gauge at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    let reads = 0
    await page.route('**/api/llm-providers/17/quota', route => {
      reads += 1
      return route.fulfill({ json: { windows: [{ name: 'monthly_budget', remaining: 999987.5,
        limit: 1000000, unit: 'USD' }], checked_at: snapshot().checked_at } })
    })
    const item = {
      key: 'fireworks', code: 'fireworks', display_name: 'Fireworks AI', auth_type: 'api_key',
      api_key_required: true, supports_quota: true, configuration_fields: [],
      connection: { id: 17, api_key_configured: true, is_active: false, configuration: {}, updated_at: null },
    }
    await mount(page, 'app/llm/components/ProviderConfigPanel.vue', {
      props: { item, detail: null }, containerStyle: { height: '900px', display: 'flex', flexDirection: 'column' },
    })
    await expect(page.getByLabel('Token / API key', { exact: true })).toBeVisible()
    await expect(page.getByText('Available balance', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'View my Fireworks balance' })).toHaveCount(0)
    await expect(page.getByText(/^Remaining:/)).toHaveCount(0)
    await expect(page.getByRole('progressbar')).toHaveCount(0)
    expect(reads).toBe(0)
  })

  test(`credits, overages and balances preserve their meaning at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    let response = {
      scope: 'account', checked_at: snapshot().checked_at,
      windows: [{ name: 'credits', unit: 'credits', used: 12000, limit: 10000,
        remaining: -2000, used_percent: 120, window_seconds: null, resets_at: snapshot().windows[0].resets_at }],
    }
    await page.route('**/api/llm-providers/17/quota', route => route.fulfill({ json: response }))
    await mount(page, 'app/llm/components/ProviderQuotaPanel.vue', { props: { providerId: 17 } })
    await expect(page.getByText('120% used', { exact: true })).toBeVisible()
    await expect(page.getByText('Used: 12,000 credits', { exact: true })).toBeVisible()
    await expect(page.getByText('Limit: 10,000 credits', { exact: true })).toBeVisible()
    await expect(page.getByText('Remaining: -2,000 credits', { exact: true })).toBeVisible()
    const progress = page.getByRole('progressbar')
    await expect(progress).toHaveAttribute('aria-valuenow', await progress.getAttribute('aria-valuemax'))
    response = { ...response, scope: 'api_key', windows: [{ name: 'budget', unit: 'USD', used: 2.5,
      limit: null, remaining: null, used_percent: null, window_seconds: null, resets_at: null }] }
    await page.getByRole('button', { name: 'Refresh limits' }).click()
    await expect(page.getByText(/Usage and budget for the configured API key/)).toBeVisible()
    await expect(page.getByText(/Used: USD\s+2.50/)).toBeVisible()
    await expect(page.getByRole('progressbar')).toHaveCount(0)
    await expect(page.getByText(/^Limit:/)).toHaveCount(0)
    response = { ...response, scope: 'account', windows: [
      { name: 'balance', unit: 'USD', remaining: 0, used_percent: null },
      { name: 'balance', unit: 'CNY', remaining: 12.3, used_percent: null },
    ] }
    await page.getByRole('button', { name: 'Refresh limits' }).click()
    await expect(page.getByText(/Remaining: USD\s+0.00/)).toBeVisible()
    await expect(page.getByText(/Remaining: CNY\s+12.30/)).toBeVisible()
    await expect(page.getByRole('progressbar')).toHaveCount(0)
  })
}

for (const code of ['elevenlabs', 'synthetic']) {
  test(`${code} declares its quota panel and hides permission help after recovery`, async ({ page }) => {
    let reads = 0
    let status = 403
    await page.route('**/api/llm-providers/17/quota', route => {
      if (status !== 200) return route.fulfill({ status, json: { detail: 'Unavailable' } })
      reads += 1
      return route.fulfill({ json: snapshot(reads * 10) })
    })
    const item = {
      key: code, code, display_name: 'Synthetic provider', auth_type: 'api_key',
      api_key_required: true, supports_quota: true,
      configuration_fields: [],
      connection: { id: 17, api_key_configured: true, is_active: false, configuration: {}, updated_at: null },
    }
    await mount(page, 'app/llm/components/ProviderConfigPanel.vue', {
      props: { item, detail: null }, containerStyle: { height: '900px', display: 'flex', flexDirection: 'column' },
    })
    const permissionHint = page.getByText('To display usage, enable User → Read in your ElevenLabs API key permissions.', { exact: true })
    await expect(page.getByRole('alert').filter({ hasText: 'Limits unavailable' })).toBeVisible()
    await expect(permissionHint).toHaveCount(code === 'elevenlabs' ? 1 : 0)
    if (code === 'elevenlabs') await expect(permissionHint).toBeVisible()
    await expect(page.getByRole('progressbar')).toHaveCount(0)
    status = 200
    await page.getByRole('button', { name: 'Refresh limits' }).click()
    await expect(page.getByText('10% used', { exact: true })).toBeVisible()
    await expect(permissionHint).toHaveCount(0)
    await page.evaluate(next => window.testApp.setProps({ item: next }), {
      ...item, connection: { ...item.connection, updated_at: '2033-05-18T03:33:20Z' },
    })
    await expect(page.getByText('20% used', { exact: true })).toBeVisible()
    await page.evaluate(next => window.testApp.setProps({ item: next }), { ...item, supports_quota: false })
    await expect(page.getByText('Usage and credits', { exact: true })).toHaveCount(0)
  })
}

test('changing provider ignores a late response from the previous account', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/llm-providers/17/quota', async route => {
    await pending
    await route.fulfill({ json: snapshot(99) }).catch(() => {})
  })
  await page.route('**/api/llm-providers/18/quota', route => route.fulfill({ json: snapshot(12) }))
  await mount(page, 'app/llm/components/ProviderQuotaPanel.vue', { props: { providerId: 17 } })
  await expect(page.getByRole('status')).toHaveText('Loading limits…')
  await page.evaluate(() => window.testApp.setProps({ providerId: 18 }))
  await expect(page.getByText('12% used', { exact: true })).toBeVisible()
  release()
  await expect(page.getByText('99% used', { exact: true })).toHaveCount(0)
})
