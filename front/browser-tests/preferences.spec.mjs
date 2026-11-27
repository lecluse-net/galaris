import { test, expect, mount, setPrivileges, jsonRoute } from './fixtures.mjs'

test('platform SMTP editors can test the saved relay with a recipient entered on the page', async ({ page }, testInfo) => {
  const address = 'smtp-test@example.invalid'
  const sends = []
  await jsonRoute(page, '**/api/llm-budget/me', {
    account: { user_id: 1, label: 'Test User', referrer_user_id: null, envelopes: [], requests: [] },
    can_configure: false,
  })
  const saved = new Map([
    ['PLATFORM_SMTP_HOST', 'smtp.example.invalid'],
    ['PLATFORM_SMTP_SECURITY', 'starttls'],
    ['PLATFORM_SMTP_AUTHENTICATION', 'auto'],
    ['PLATFORM_SMTP_USERNAME', 'synthetic-smtp-user'],
  ])
  const param = ([name, value]) => ({ name, value, configured: true, secret: false, prompt: null })
  await page.route('**/api/params', route => route.fulfill({ json: { params: Array.from(saved, param) } }))
  await page.route('**/api/params/PLATFORM_SMTP_*', route => {
    const name = new URL(route.request().url()).pathname.split('/').at(-1)
    const { value } = route.request().postDataJSON()
    saved.set(name, value)
    return route.fulfill({ json: { ...param([name, value]), status: 'success' } })
  })
  await page.route('**/api/auth/platform-smtp/test', route => {
    sends.push(route.request().postDataJSON())
    if (sends.length === 1) return route.fulfill({ status: 502, json: { detail: 'The relay rejected the test email.' } })
    return route.fulfill({ status: 204 })
  })
  await mount(page, 'core/params/components/PreferencesSectionPage.vue', {
    props: { section: 'system' }, route: '/params/system', privileges: ['PARAMS_ACCESS'], shell: true,
  })
  const block = page.getByRole('region', { name: 'Platform SMTP', exact: true })
  const recipient = block.getByRole('textbox', { name: 'Recipient email', exact: true })
  const send = block.getByRole('button', { name: 'Send test email', exact: true })
  await expect(recipient).toHaveCount(0)
  await setPrivileges(page, ['PARAMS_EDIT'])
  await expect(recipient).toBeEditable()
  const security = block.getByRole('combobox', { name: 'Connection security' })
  await security.click()
  await page.getByRole('option', { name: 'SSL/TLS', exact: true }).click()
  await expect.poll(() => saved.get('PLATFORM_SMTP_SECURITY')).toBe('tls')
  const authentication = block.getByRole('combobox', { name: 'Authentication method' })
  await authentication.click()
  await page.getByRole('option', { name: 'No authentication', exact: true }).click()
  const username = block.getByRole('textbox', { name: 'SMTP username' })
  await expect(username).toHaveCount(0)
  await authentication.click()
  await page.getByRole('option', { name: 'Normal password', exact: true }).click()
  await expect(username).toHaveValue('synthetic-smtp-user')
  await expect.poll(() => saved.get('PLATFORM_SMTP_AUTHENTICATION')).toBe('password')
  await recipient.fill(address)
  await send.click()
  await expect(page.getByText('The relay rejected the test email.', { exact: true })).toBeVisible()
  await expect(recipient).toHaveValue(address)
  await recipient.press('Enter')
  await expect(page.getByText('The SMTP relay accepted the test email.', { exact: true })).toBeVisible()
  expect(sends).toEqual([{ recipient: address }, { recipient: address }])
  await block.screenshot({ path: testInfo.outputPath('platform-smtp-light.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.testApp.dark(true))
  await block.screenshot({ path: testInfo.outputPath('platform-smtp-mobile-dark.png') })
})

test('personal chat display preferences require an enabled accessible chat and retain the saved choice on failure', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('access_token', 'component-test'))
  let enabled = false
  let fail = false
  let user = { id: 1, email: 'test@example.invalid', display_name: 'Test User', language: 'en', document_open_mode: 'split' }
  await page.route('**/api/chat/status', route => route.fulfill({ json: { enabled } }))
  await jsonRoute(page, '**/api/mail/status', { enabled: false })
  await jsonRoute(page, '**/api/chat/identities', [])
  await jsonRoute(page, '**/api/auth/mfa/status', { enabled: false, setup_pending: false, recovery_codes_remaining: 0 })
  await jsonRoute(page, '**/api/llm/me/options?include_native_voices=false', { profiles: [], current_profile_id: null, voices: [] })
  await jsonRoute(page, '**/api/llm/me/native-voices', { native_voices: [] })
  await jsonRoute(page, '**/api/llm/me/preferences', { profile_id: null, voice_llm_id: null, voice_mode: 'tts', voice_code: null })
  await page.route('**/api/auth/me', route => {
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
    user = { ...user, ...route.request().postDataJSON() }
    return route.fulfill({ json: user })
  })
  await mount(page, 'core/authorize/pages/profile.vue', { privileges: ['CHAT_ACCESS'] })
  const select = page.getByLabel('Chat document opening mode', { exact: true })
  const field = page.locator('.q-field').filter({ has: select })
  await expect(select).toHaveCount(0)
  enabled = true
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(select).toBeVisible()
  await expect(field).toContainText('Split screen')
  await select.click()
  await page.getByRole('option', { name: 'Dialog', exact: true }).click()
  await expect.poll(() => user.document_open_mode).toBe('dialog')
  await expect(field).toContainText('Dialog')
  fail = true
  await select.click()
  await page.getByRole('option', { name: 'Split screen', exact: true }).click()
  await expect(page.getByText('Error while updating', { exact: true })).toBeVisible()
  await expect(field).toContainText('Dialog')
  fail = false
  await select.click()
  await page.getByRole('option', { name: 'Split screen', exact: true }).click()
  await expect.poll(() => user.document_open_mode).toBe('split')
  await setPrivileges(page, [])
  await expect(select).toHaveCount(0)
  await setPrivileges(page, ['CHAT_ACCESS'])
  await expect(field).toContainText('Split screen')
  enabled = false
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(select).toHaveCount(0)
})

for (const [name, label, privileges] of [
  ['ai.executor-system-prompt', 'Task executor', ['INSTRUCTION_CONFIG_EDIT']],
  ['ai.goal-tracking-system-prompt', 'Goal tracking prompt', ['GOAL_CONFIG_EDIT']],
  ['audio.summary-meeting-final-system-prompt', 'Meeting reports', ['AUDIO_CONFIG_EDIT']],
  ['audio.summary-video-final-system-prompt', 'YouTube video summaries', ['AUDIO_CONFIG_EDIT']],
]) {
test(`${name}: customization displays a diff, persists choices and respects revoked rights`, async ({ page }) => {
  let param = { name, value: 'Custom instructions', secret: false, configured: true,
    prompt: { default_value: 'Default instructions', customized: true, default_changed: true } }
  const requests = []
  await page.route(`**/api/params/${name}`, route => {
    expect(route.request().method()).toBe('PUT')
    const body = route.request().postDataJSON()
    requests.push(body)
    param = { ...param, value: body.prompt_action === 'use_default' ? param.prompt.default_value : body.value,
      prompt: { ...param.prompt, default_changed: false, customized: body.prompt_action !== 'use_default' } }
    return route.fulfill({ json: { ...param, status: 'ok' } })
  })
  await page.route('**/api/params', route => route.fulfill({ json: { params: [param] } }))
  await mount(page, 'core/params/components/PreferencesSectionPage.vue', {
    props: { section: 'instructions' }, route: '/params/instructions', privileges,
  })
  const block = page.getByRole('region', { name: label, exact: true })
  await block.getByRole('button', { name: `Expand "${label}"`, exact: true }).click()
  const editor = block.locator('textarea:visible')
  await expect(editor).toHaveValue('Custom instructions')
  await page.getByRole('button', { name: 'Show differences', exact: true }).click()
  await expect(page.locator('.prompt-editor__diff-line--removed')).toContainText('Default instructions')
  await expect(page.locator('.prompt-editor__diff-line--added')).toContainText('Custom instructions')
  await page.getByRole('button', { name: 'Keep my version', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toMatchObject({ value: 'Custom instructions', prompt_action: 'keep_custom' })
  await editor.fill('Changed by the user')
  await page.getByRole('button', { name: 'Save customization', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toEqual({ value: 'Changed by the user', clear_secret: false })
  await page.getByRole('button', { name: 'Restore default', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Use default', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toMatchObject({ value: null, prompt_action: 'use_default' })
  await expect(editor).toHaveValue('Default instructions')
  await setPrivileges(page, privileges.map(code => code.replace('_EDIT', '_ACCESS')))
  // Refreshing privileges remounts the page with its advanced sections closed.
  await block.getByRole('button', { name: `Expand "${label}"`, exact: true }).click()
  await expect(editor).toBeVisible()
  await expect(editor).not.toBeEditable()
  await expect(page.getByRole('button', { name: 'Save customization', exact: true })).toBeDisabled()
  await setPrivileges(page, [])
  await expect(page.locator('.settings-panel')).toHaveCount(0)
})
}

// Keyboard navigation and attribution safety move with the links to About.
test('sidebar footer exposes its build version and About remains reachable in compact mode', async ({ page }) => {
  await mount(page, 'app/index/components/SidebarFooter.vue')
  await expect(page.getByText('test-release', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'About', exact: true }).press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/about')
  await page.evaluate(() => window.testApp.setProps({ compact: true }))
  await page.evaluate(() => window.testApp.navigate('/'))
  await page.getByRole('link', { name: 'About', exact: true }).press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/about')
})

test('About provides public access to the license and preserves safe author attribution', async ({ page }) => {
  await mount(page, 'app/index/pages/about.vue', { authenticated: false })
  await expect(page.getByRole('heading', { name: 'Galaris', exact: true })).toBeVisible()
  await expect(page.getByText('Current version', { exact: true })).toBeVisible()
  await expect(page.getByText('test-release', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'License', exact: true }).press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/license')
  await expect(page.locator('a[href="https://lecluse.net"]')).toHaveAttribute('rel', 'noopener noreferrer')
})

test('sidebar logo navigates home and compact mode changes the rendered drawer', async ({ page }) => {
  await mount(page, 'app/index/components/Sidebar.vue', { route: '/task' })
  const logo = page.locator('a.logo-section')
  await expect(logo).toHaveAccessibleName('Home')
  await logo.press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/')
  const drawer = page.locator('.q-drawer')
  const expanded = (await drawer.boundingBox()).width
  await page.getByRole('button', { name: 'Collapse sidebar', exact: true }).click()
  await expect.poll(async () => (await drawer.boundingBox()).width).toBeLessThan(expanded)
  await page.getByRole('button', { name: 'Expand sidebar', exact: true }).click()
  await expect.poll(async () => (await drawer.boundingBox()).width).toBe(expanded)
  await page.getByRole('link', { name: 'About', exact: true }).press('Enter')
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/about')
})

test('a failed parameter read stays visible until its own retry restores editable saved values', async ({ page }) => {
  let failed = true, reads = 0
  await page.route('**/api/params', route => {
    reads++
    return route.fulfill(failed ? { status: 503, json: { detail: 'Synthetic configuration outage' } }
      : { json: { params: [{ name: 'ai.executor-system-prompt', value: 'Saved instructions', secret: false, configured: true,
        prompt: { default_value: 'Default', customized: true, default_changed: false } }] } })
  })
  await jsonRoute(page, '**/api/params/unrelated', { name: 'unrelated', value: 'kept', secret: false, configured: true })
  await mount(page, 'core/params/components/PreferencesSectionPage.vue', {
    props: { section: 'instructions' }, route: '/params/instructions', privileges: ['INSTRUCTION_CONFIG_EDIT'],
  })
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('Synthetic configuration outage')
  await expect(page.locator('textarea')).toHaveCount(0)
  // A successful unrelated action must not hide the failed read.
  await page.evaluate(async () => {
    const { useParamsStore } = await import('/core/params/stores/paramsStore.ts')
    await useParamsStore(window.testApp.pinia).updateParam('unrelated', 'kept')
  })
  await expect(alert).toContainText('Synthetic configuration outage')
  failed = false
  await alert.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(alert).toHaveCount(0)
  await page.getByRole('region', { name: 'Task executor', exact: true }).getByRole('button', { name: 'Expand "Task executor"', exact: true }).click()
  await expect(page.locator('textarea:visible')).toHaveValue('Saved instructions')
  expect(reads).toBe(2)
})
