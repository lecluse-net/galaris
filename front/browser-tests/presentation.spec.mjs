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
  await expect(badge.locator('.q-icon')).toHaveText('play_arrow')
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

test('user preferences persist each theme and save a selected profile language', async ({ page }) => {
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
  }
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
