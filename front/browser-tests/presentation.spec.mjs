import { test, expect, mount, jsonRoute } from './fixtures.mjs'

for (const [browserLocale, language, loginLabel] of [
  ['en-US', 'en', 'Log in'],
  ['fr-FR', 'fr', 'Se connecter'],
  ['fr-CA', 'fr', 'Se connecter'],
  ['zh-CN', 'zh', '登录'],
  ['de-DE', 'en', 'Log in'],
]) {
  test.describe(`browser language ${browserLocale}`, () => {
    test.use({ locale: browserLocale })

    test('login follows the browser with English fallback and preserves explicit profile choices', async ({ page }) => {
      await jsonRoute(page, '**/api/auth/registration-status', { registration_open: false })
      await jsonRoute(page, '**/api/authorize/my-privileges', [])
      for (let visit = 0; visit < 2; visit++) {
        await page.goto('/test-support/browser/index.html')
        await page.waitForFunction(() => window.testApp?.mount)
        await expect(page.locator('html')).toHaveAttribute('lang', new RegExp(`^${language}(?:-|$)`))
        await page.evaluate(async () => {
          const { getLocale } = await import('/core/i18n/index.ts')
          await window.testApp.mount({ component: 'core/user/pages/login.vue', authenticated: false, locale: getLocale() })
        })
        await expect(page.getByRole('button', { name: loginLabel, exact: true })).toBeVisible()
      }

      await page.evaluate(async () => {
        const { applyUserLocale } = await import('/core/i18n/index.ts')
        applyUserLocale('fr')
      })
      await expect(page.getByRole('button', { name: 'Se connecter', exact: true })).toBeVisible()
      for (const preference of [null, 'unsupported']) {
        await page.evaluate(async preferred => {
          const { applyUserLocale } = await import('/core/i18n/index.ts')
          applyUserLocale(preferred)
        }, preference)
        await expect(page.locator('html')).toHaveAttribute('lang', new RegExp(`^${language}(?:-|$)`))
        await expect(page.getByRole('button', { name: loginLabel, exact: true })).toBeVisible()
      }
    })
  })
}

test('status badges expose the current state even without an icon', async ({ page }) => {
  await mount(page, 'core/util/components/StatusBadge.vue', { props: { label: 'Running', tone: 'active', icon: 'play_arrow' } })
  const badge = page.locator('.q-badge')
  await expect(badge).toContainText('Running')
  await page.evaluate(() => window.testApp.setProps({ tone: 'success', label: 'Completed', icon: undefined }))
  await expect(badge).toContainText('Completed')
  await expect(badge).not.toContainText('Running')
  await expect(badge.locator('.q-icon')).toHaveCount(0)
})

test('login rejects an invalid email before making an authentication request', async ({ page }) => {
  await jsonRoute(page, '**/api/auth/registration-status', { registration_open: false })
  await mount(page, 'core/user/pages/login.vue', { authenticated: false })
  await page.evaluate(() => window.testApp.dark(true))
  await expect(page.locator('.auth-card__title')).toBeVisible()
  await page.getByLabel('Email', { exact: true }).fill('invalid')
  await page.getByLabel('Password', { exact: true }).fill('example')
  await page.getByRole('button', { name: /sign in|log in/i }).click()
  await expect(page.locator('.q-field--error')).toHaveCount(1)
})

async function expectBrowserTheme(page, dark) {
  await expect(page.locator('html')).toHaveCSS('color-scheme', dark ? 'dark' : 'light')
  const background = await page.locator('body').evaluate(body => getComputedStyle(body).backgroundColor)
  await expect(page.locator('html')).toHaveCSS('background-color', background)
  const themeColor = page.locator('meta[name="theme-color"]')
  await expect(themeColor).toHaveCount(1)
  await expect(themeColor).toHaveAttribute('content', background)
}

test('user preferences persist each theme and save a selected profile language', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ colorScheme: 'light' })
  const updates = []
  await page.route('**/api/auth/me', async route => {
    expect(route.request().method()).toBe('PUT')
    updates.push(route.request().postDataJSON())
    await route.fulfill({ json: { id: 1, email: 'test@example.invalid', display_name: 'Test User', language: updates.at(-1).language } })
  })
  await mount(page, 'core/user/components/UserMenu.vue')
  await page.getByRole('button', { name: 'My account', exact: true }).click()
  const buttons = page.locator('.q-btn-toggle button')
  for (const [index, mode, dark] of [[2, 'dark', true], [1, 'light', false], [0, 'auto', false]]) {
    await buttons.nth(index).click()
    await expect.poll(() => page.evaluate(() => localStorage.getItem('theme_mode'))).toBe(mode)
    await expect(page.locator('body')).toHaveClass(dark ? /body--dark/ : /body--light/)
    await expectBrowserTheme(page, dark)
  }
  await page.emulateMedia({ colorScheme: 'dark' })
  await expectBrowserTheme(page, true)
  await page.emulateMedia({ colorScheme: 'light' })
  await expectBrowserTheme(page, false)
  await buttons.nth(2).click()
  await expectBrowserTheme(page, true)
  await mount(page, 'core/user/components/UserMenu.vue')
  await expectBrowserTheme(page, true)
  await page.emulateMedia({ colorScheme: 'dark' })
  await expectBrowserTheme(page, true)
  await page.emulateMedia({ colorScheme: 'light' })
  await expectBrowserTheme(page, true)
  for (const event of ['pageshow', 'visibilitychange']) {
    await page.evaluate(name => {
      document.querySelector('meta[name="theme-color"]').remove()
      const target = name === 'pageshow' ? window : document
      target.dispatchEvent(new Event(name))
    }, event)
    await expectBrowserTheme(page, true)
  }
  await page.getByRole('button', { name: 'My account', exact: true }).click()
  await page.locator('.q-item').filter({ hasText: 'Language' }).click()
  await expect(page.locator('.language-menu-list .q-item')).toHaveCount(3)
  await page.locator('.language-menu-list .q-item').filter({ hasText: 'Français' }).click()
  await expect.poll(() => updates).toEqual([{ language: 'fr' }])
  await expect(page.getByText('Langue', { exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('user'))?.language)).toBe('fr')
})

test('navigation translates tooltips, retains literal descriptions and follows links', async ({ page }) => {
  await mount(page, 'core/navigation/components/LeftMenuItems.vue', {
    props: { parentPath: '', depth: 0, tree: {
      translated: { label: 'nav.skills', description: 'nav.skills_desc', to: '/skill', icon: 'psychology' },
      literal: { label: 'Example', description: 'Literal description', to: '/example', icon: 'home' },
    } },
  })
  const translated = page.locator('a[href="/skill"]')
  await expect(translated).toHaveAttribute('title', /.+/)
  expect(await translated.getAttribute('title')).not.toBe('nav.skills_desc')
  await expect(page.locator('a[href="/example"]')).toHaveAttribute('title', 'Literal description')
  await expect(page.getByText('Literal description', { exact: true })).toHaveCount(0)
  await translated.click()
  await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.path)).toBe('/skill')
})

test('Markdown compact frontmatter renders metadata and keeps the body and tables', async ({ page }) => {
  await mount(page, 'core/util/components/Markdown.vue', { props: {
    compactFrontmatter: true,
    content: '---\nname: sample-skill\ndescription: An example\n---\n\n# Procedure\n\n| A | B |\n|---|---|\n| one | two |',
  } })
  await expect(page.locator('table.markdown-frontmatter')).toContainText('sample-skill')
  await expect(page.getByRole('heading', { name: 'Procedure' })).toBeVisible()
  await expect(page.locator('table').last()).toContainText('one')
  await page.evaluate(() => window.testApp.setProps({ content: '# No metadata' }))
  await expect(page.locator('table.markdown-frontmatter')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'No metadata' })).toBeVisible()
})

test('streaming chat reuses date formatters across existing messages', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    window.chatDateFormatters = 0
    Intl.DateTimeFormat = new Proxy(Intl.DateTimeFormat, {
      construct(target, args) { window.chatDateFormatters++; return Reflect.construct(target, args) },
    })
  })
  await page.route('**/api/chat/rooms/performance-room/speech/status*', route => route.fulfill({ json: { available_agent_ids: [] } }))
  const messages = Array.from({ length: 100 }, (_, index) => ({
    id: `message-${index}`, external_id: `message-${index}`, text: `Synthetic message ${index}`, files: [],
    sender: { display_name: 'Test', is_ai: false }, created_at: '2026-01-01T12:00:00Z', is_mine: true,
  }))
  await mount(page, 'app/chat/components/MessageTimeline.vue', { props: {
    roomId: 'performance-room', messages, activity: [], liveRound: null, agentId: 7, agentName: 'Test', showAgentAvatars: false,
  } })
  await expect(page.locator('.message-meta time')).toHaveCount(100)
  const initialFormatters = await page.evaluate(() => window.chatDateFormatters)
  for (const text of ['First fragment', 'Second fragment', 'Final fragment']) {
    await page.evaluate(result => window.testApp.setProps({ liveRound: {
      room_id: 'performance-room', round_id: 'synthetic-round', topic_id: null, active: true, success: true,
      last_sequence: 1, ai_result: { prompt: '', system_prompt: '', result, messages: [{ type: 'text', content: result }], tools_used: [], cost: 0, execution_time: 0, success: true },
    } }), text)
    await expect(page.locator('.message-bubble--live')).toContainText(text)
  }
  const streamedFormatters = await page.evaluate(() => window.chatDateFormatters)
  const englishDate = await page.locator('.message-meta time').first().textContent()
  await page.evaluate(async () => { const { setLocale } = await import('/core/i18n/index.ts'); setLocale('fr') })
  await expect(page.locator('.message-meta time').first()).not.toHaveText(englishDate)
  await testInfo.attach('chat-date-format-cost', { body: JSON.stringify({ initialFormatters, streamedFormatters, messages: 100 }), contentType: 'application/json' })
  expect(initialFormatters).toBeLessThan(10)
  expect(streamedFormatters).toBeLessThan(10)
})

test('chat text preserves Unicode, links and code during updates without fragmenting prose into character nodes', async ({ page }, testInfo) => {
  await mount(page, 'app/chat/components/SafeMessageContent.vue', { props: { content: 'Ready' } })
  await expect(page.getByText('Ready', { exact: true })).toBeVisible()
  await page.evaluate(() => {
    const original = document.createTextNode.bind(document)
    window.chatTextAllocations = 0
    document.createTextNode = text => { window.chatTextAllocations++; return original(text) }
  })
  const plain = 'Synthetic ordinary text. '.repeat(500)
  await page.evaluate(content => window.testApp.setProps({ content }), plain)
  await expect(page.locator('.safe-message-content p')).toHaveText(plain.trim())
  const plainAllocations = await page.evaluate(() => window.chatTextAllocations)
  await page.evaluate(() => { window.chatTextAllocations = 0 })
  const emojiText = `${plain}👩🏽‍💻🇫🇷1️⃣ ${plain}`
  await page.evaluate(content => window.testApp.setProps({ content }), `${emojiText}\n\n[Reference](https://example.invalid) and \`literal 😀\`.`)
  await expect(page.getByRole('link', { name: 'Reference', exact: true })).toHaveAttribute('href', 'https://example.invalid')
  await expect(page.locator('.safe-message-content p').first()).toHaveText(emojiText.trim())
  await expect(page.locator('.safe-message-content code')).toHaveText('literal 😀')
  await expect(page.locator('.chat-message-emoji')).toHaveText(['👩🏽‍💻', '🇫🇷', '1️⃣'])
  const mixedAllocations = await page.evaluate(() => window.chatTextAllocations)
  const textNodes = await page.locator('.safe-message-content').evaluate(element => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
    let count = 0
    while (walker.nextNode()) count++
    return count
  })
  await testInfo.attach('chat-text-cost', { body: JSON.stringify({ plainAllocations, mixedAllocations, textNodes }), contentType: 'application/json' })
  // Bound linear DOM growth, without prescribing an exact presentation tree.
  expect(plainAllocations).toBeLessThan(100)
  expect(mixedAllocations).toBeLessThan(100)
  expect(textNodes).toBeLessThan(100)
})

test('conversation plans preserve HTML structure alongside Markdown and filter active content', async ({ page }, testInfo) => {
  await mount(page, 'app/chat/components/SafeMessageContent.vue', { props: {
    content: '🛠️ Background plan\n\n🎯 What I understood\n'
      + '<h2>Prepare the catalogue</h2><p>Keep <strong>existing entries</strong> and <code>revision</code>.</p>'
      + '<ol><li>Read the source<ul><li>Check the <a href="https://example.invalid/source">reference</a>.</li></ul></li>'
      + '<li>Update the catalogue.</li></ol><p>Preserve all links.</p>\n\n'
      + '🧭 My approach\n\n**Verify each item.**\n\n1. Inventory\n2. Reconcile\n\n'
      + '<script>window.planScriptExecuted = true</script><img src="data:image/png;base64," onerror="window.planScriptExecuted = true">',
  } })
  const content = page.locator('.safe-message-content')
  await expect(content.getByRole('heading', { name: 'Prepare the catalogue', exact: true })).toBeVisible()
  await expect(content.locator('p').filter({ hasText: 'Keep existing entries and revision.' })).toBeVisible()
  await expect(content.locator('strong').filter({ hasText: 'existing entries' })).toBeVisible()
  await expect(content.locator('code')).toHaveText('revision')
  await expect(content.getByRole('listitem')).toHaveCount(5)
  await expect(content.getByRole('link', { name: 'reference' })).toHaveAttribute('href', 'https://example.invalid/source')
  await expect(content).not.toContainText('# Strong')
  await expect(content.locator('script, [onerror]')).toHaveCount(0)
  expect(await page.evaluate(() => window.planScriptExecuted)).toBeUndefined()
  await page.screenshot({ path: testInfo.outputPath('conversation-plan-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(content.getByRole('link', { name: 'reference' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('conversation-plan-mobile.png'), fullPage: true })

  await page.evaluate(() => window.testApp.setProps({ content: '<execution_context>\nTask details\n</execution_context>\n\n<plan-shared-context>\nMission\n</plan-shared-context>\n\n```xml\n<p>Literal source</p>\n```' }))
  await expect(content.getByRole('heading', { name: 'Execution_context', exact: true })).toBeVisible()
  await expect(content.getByRole('heading', { name: 'Plan shared context', exact: true })).toBeVisible()
  await expect(content.getByRole('textbox')).toHaveValue('<p>Literal source</p>')
})
