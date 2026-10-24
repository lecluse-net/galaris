import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const [locale, language, label] of [
  ['en-US', 'en', 'Log in'],
  ['fr-FR', 'fr', 'Se connecter'],
  ['zh-CN', 'zh', '登录'],
]) {
  test.describe(`production bootstrap in ${locale}`, () => {
    test.use({ locale })
    test('the first login keeps its translated label and document language after Quasar installation', async ({ page }) => {
      const errors = collectPageErrors(page)
      const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
      await page.goto('/user/login')
      await refresh
      await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible()
      await expect(page.locator('html')).toHaveAttribute('lang', new RegExp(`^${language}(?:-|$)`))
      await page.locator('input[type=email]').fill('synthetic@example.invalid')
      await expect(page.locator('html')).toHaveAttribute('lang', new RegExp(`^${language}(?:-|$)`))
      expect(errors()).toEqual([])
    })
  })
}
