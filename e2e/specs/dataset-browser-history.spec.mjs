import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const width of [1440, 390]) {
  test(`Data uses common document navigation and retains invalid drafts at ${width}px`, async ({ page, request }) => {
    const errors = collectPageErrors(page)
    const fixture = await (await request.post('/api/__test/seed')).json()
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/user/login')
    await page.locator('input[type=email]').fill(fixture.email)
    await page.locator('input[type=password]').fill(fixture.password)
    const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
    await page.locator('button[type=submit]').click()
    const session = await (await login).json()
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    const headers = { Authorization: `Bearer ${session.access_token}` }
    const response = await request.post('/api/datasets', { headers, data: { title: 'Synthetic navigation Data', content: '{"value":"Alpha"}' } })
    expect(response.ok(), await response.text()).toBeTruthy()
    const item = await response.json()
    await errors.settle()
    await page.goto(`/dataset/${item.id}`)
    const json = page.locator('textarea.code-editor')
    await expect(json).toHaveValue('{"value":"Alpha"}')
    await expect(page).toHaveURL(new RegExp(`document_id=${item.id}$`))
    await json.fill('{')
    await expect(page.getByRole('status', { name: /Corrigez les champs invalides|Fix invalid fields/ })).toBeVisible()
    // A full reload keeps the local draft; the server still holds valid JSON.
    await page.reload()
    await expect(json).toHaveValue('{')
    expect((await (await request.get(`/api/datasets/${item.id}`, { headers })).json()).content).toBe('{"value":"Alpha"}')
    await json.fill('{"value":"Beta"}')
    await expect.poll(async () => (await (await request.get(`/api/datasets/${item.id}`, { headers })).json()).content).toBe('{"value":"Beta"}')
    await page.reload()
    await expect(json).toHaveValue('{"value":"Beta"}')
    expect(errors()).toEqual([])
  })
}
