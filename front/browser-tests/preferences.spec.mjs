import { test, expect, mount, setPrivileges, jsonRoute } from './fixtures.mjs'

test('personal chat display preferences require an enabled accessible chat and retain the saved choice on failure', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('access_token', 'component-test'))
  let enabled = false
  let fail = false
  let user = { id: 1, email: 'test@example.invalid', display_name: 'Test User', language: 'en', document_open_mode: 'split' }
  await page.route('**/api/chat/status', route => route.fulfill({ json: { enabled } }))
  await jsonRoute(page, '**/api/mail/status', { enabled: false })
  await jsonRoute(page, '**/api/chat/identities', [])
  await jsonRoute(page, '**/api/auth/mfa/status', { enabled: false, setup_pending: false, recovery_codes_remaining: 0 })
  await jsonRoute(page, '**/api/llm/me/options', { profiles: [], voices: [], native_voices: [] })
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

test('prompt customization displays a diff, persists choices and respects revoked rights', async ({ page }) => {
  const name = 'ai.executor-system-prompt'
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
  await mount(page, 'core/params/components/PromptSettingEditor.vue', { props: { field: { name, input: 'prompt', labelKey: 'promptEditor.content' } }, privileges: ['PARAMS_EDIT'] })
  await page.evaluate(param => window.testApp.patchStore('core/params/stores/paramsStore.ts', 'useParamsStore', { params: [param] }), param)
  const editor = page.locator('textarea')
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
  await setPrivileges(page, [])
  await expect(editor).not.toBeEditable()
  await expect(page.getByRole('button', { name: 'Save customization', exact: true })).toBeDisabled()
})

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
  await expect(page.getByRole('heading', { name: 'About', exact: true })).toBeVisible()
  await expect(page.getByText('Version: test-release', { exact: true })).toBeVisible()
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
