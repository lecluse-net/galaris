import { test, expect, mount, setPrivileges, jsonRoute } from './fixtures.mjs'

const catalog = [
  ...['ultra-low', 'low', 'standard', 'high', 'default'].map(tier => ({ id: `profile1/text/${tier}` })),
  { id: 'profile2/text/low' },
  { id: 'vectors/embedding/default' },
  { id: 'profile1/decision/default' },
]

async function prepareTokens(page) {
  await jsonRoute(page, '**/api/auth/me/tokens', [{
    id: 1, user_id: 1, label: 'Synthetic client token', token: 'ut_masked...not-a-secret',
    enabled: true, created_at: '2026-01-01T12:00:00Z',
  }])
  await page.addInitScript(() => {
    window.copiedConfigs = []
    window.failCopy = false
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
      async writeText(value) {
        if (window.failCopy) throw new Error('Clipboard unavailable')
        window.copiedConfigs.push(value)
      },
    } })
  })
}

for (const mobile of [false, true]) {
  test(`tokens generate copyable profile configs without retrieving a token (${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 })
    await prepareTokens(page)
    let catalogRequests = 0
    await page.route('**/api/profile/models', route => {
      catalogRequests += 1
      return route.fulfill({ json: { data: catalog } })
    })
    await mount(page, 'core/user/pages/tokens.vue', { privileges: ['LLM_API_ACCESS'] })
    const open = page.getByRole('button', { name: 'Configure Codex / Claude Code', exact: true })
    await expect(open).toBeVisible()
    expect(catalogRequests).toBe(0)
    for (const protocol of ['openai', 'anthropic']) {
      const url = `${new URL(page.url()).origin}/api/profile/${protocol}`
      const card = page.locator('.api-endpoint-card').filter({ has: page.getByText(url, { exact: true }) })
      await card.getByRole('button', { name: 'Copy the base URL', exact: true }).click()
      expect(await page.evaluate(() => window.copiedConfigs.at(-1))).toBe(url)
    }
    await open.click()
    const dialog = page.getByRole('dialog')
    const content = dialog.getByLabel('Configuration to copy', { exact: true })
    await expect(content).toHaveValue(/profile1\/text\/high/)
    const claude = JSON.parse(await content.inputValue())
    expect(claude.model).toBe('profile1/text/high')
    expect(claude.env.ANTHROPIC_BASE_URL).toBe(`${new URL(page.url()).origin}/api/profile/anthropic`)
    expect(claude.env.ANTHROPIC_DEFAULT_HAIKU_MODEL).toBe('profile1/text/ultra-low')
    expect(claude.env.ANTHROPIC_DEFAULT_OPUS_MODEL).toBe('profile1/text/standard')
    expect(claude.env.ANTHROPIC_AUTH_TOKEN).toBeUndefined()
    const auth = JSON.parse(await dialog.getByLabel('Authentication to complete', { exact: true }).inputValue())
    expect(auth.env.ANTHROPIC_AUTH_TOKEN).toBe('<GALARIS_API_TOKEN>')
    await dialog.getByRole('button', { name: 'Copy configuration', exact: true }).click()
    expect(await page.evaluate(() => window.copiedConfigs.at(-1))).toBe(await content.inputValue())
    await dialog.getByRole('tab', { name: 'Codex', exact: true }).click()
    const codex = await content.inputValue()
    expect(codex).toContain('model = "profile1/text/high"')
    expect(codex).toContain(`base_url = "${new URL(page.url()).origin}/api/profile/openai"`)
    expect(codex).toContain('wire_api = "responses"')
    expect(codex).toContain('env_key = "GALARIS_API_TOKEN"')
    expect(codex).not.toContain('ut_masked')
    await dialog.getByRole('button', { name: 'Copy authentication template', exact: true }).click()
    expect(await page.evaluate(() => window.copiedConfigs.at(-1))).toBe("export GALARIS_API_TOKEN='<GALARIS_API_TOKEN>'\n")

    await dialog.getByLabel('Profile', { exact: true }).click()
    await expect(page.getByRole('option')).toHaveCount(2)
    await page.getByRole('option', { name: 'profile2', exact: true }).click()
    await expect(content).toHaveValue(/model = "profile2\/text\/low"/)
    await dialog.getByRole('tab', { name: 'Claude Code', exact: true }).click()
    const second = JSON.parse(await content.inputValue())
    expect(second.model).toBe('profile2/text/low')
    for (const alias of ['HAIKU', 'SONNET', 'OPUS', 'FABLE']) {
      expect(second.env[`ANTHROPIC_DEFAULT_${alias}_MODEL`]).toBe('profile2/text/low')
    }
    await expect(dialog.getByText('For missing tiers, Claude Code aliases use the selected startup model.')).toBeVisible()
    await page.evaluate(() => { window.failCopy = true })
    await dialog.getByRole('button', { name: 'Copy configuration', exact: true }).click()
    await expect(page.getByText('Unable to copy. You can select the text manually.')).toBeVisible()
    // The shared mobile dialog layout fills the viewport; its header closes it.
    if (mobile) await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
    else await page.mouse.click(3, 3)
    await expect(dialog).toHaveCount(0)
    await open.click()
    await expect(content).toHaveValue(/profile1\/text\/high/)
    expect(catalogRequests).toBe(2)
    await setPrivileges(page, [])
    await expect(dialog).toHaveCount(0)
    await expect(open).toHaveCount(0)
  })
}

test('profile config discovery handles missing rights, failed loading, empty catalogs and reopening', async ({ page }) => {
  await prepareTokens(page)
  let response = 'error'
  let requests = 0
  await page.route('**/api/profile/models', route => {
    requests += 1
    return response === 'error'
      ? route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
      : route.fulfill({ json: { data: response === 'empty' ? [] : catalog } })
  })
  await mount(page, 'core/user/pages/tokens.vue')
  const open = page.getByRole('button', { name: 'Configure Codex / Claude Code', exact: true })
  await expect(open).toHaveCount(0)
  expect(requests).toBe(0)
  await setPrivileges(page, ['LLM_API_ACCESS'])
  await open.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Unable to load profiles. Check your LLM API access and retry.')).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Copy configuration', exact: true })).toHaveCount(0)
  response = 'empty'
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.getByText('No profile offers an available text model. Assign an active model to a text tier in LLM usages.')).toBeVisible()
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  response = 'ready'
  await open.click()
  await expect(dialog.getByLabel('Configuration to copy', { exact: true })).toHaveValue(/profile1\/text\/high/)
})

test('closing during discovery cannot restore an old profile selection on reopening', async ({ page }) => {
  await prepareTokens(page)
  let firstRequest
  let calls = 0
  await page.route('**/api/profile/models', async route => {
    calls += 1
    if (calls === 1) {
      firstRequest = route
      return
    }
    await route.fulfill({ json: { data: [{ id: 'profile2/text/low' }] } })
  })
  await mount(page, 'core/user/pages/tokens.vue', { privileges: ['LLM_API_ACCESS'] })
  const open = page.getByRole('button', { name: 'Configure Codex / Claude Code', exact: true })
  await open.click()
  await expect.poll(() => Boolean(firstRequest)).toBe(true)
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Loading profiles…')).toBeVisible()
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  await expect(dialog).toHaveCount(0)
  await open.click()
  const content = dialog.getByLabel('Configuration to copy', { exact: true })
  await expect(content).toHaveValue(/profile2\/text\/low/)
  await firstRequest.fulfill({ json: { data: catalog } }).catch(() => {})
  await expect(content).toHaveValue(/profile2\/text\/low/)
})
