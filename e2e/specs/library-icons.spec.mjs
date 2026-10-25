import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test.use({ serviceWorkers: 'allow' })

for (const width of [1440, 390]) {
  test(`folder image uploads persist in Documents and Datasets at ${width}px`, async ({ page, request }, testInfo) => {
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
    const closeSidebar = async () => {
      if (width >= 1024) return
      await expect(page.locator('.q-drawer')).toHaveClass(/q-drawer--mobile/)
      const backdrop = page.locator('.q-drawer__backdrop')
      if (await backdrop.isVisible()) await backdrop.click({ position: { x: width - 10, y: 150 } })
      await expect(backdrop).not.toBeVisible()
    }
    const headers = { Authorization: `Bearer ${session.access_token}` }
    const raster = await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 16
      const context = canvas.getContext('2d'); context.fillStyle = '#077cc0'; context.fillRect(0, 0, 32, 16)
      return canvas.toDataURL('image/png')
    })
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="16"><path d="M0 16L16 0L32 16Z"/>${' '.repeat(100_001)}</svg>`
    for (const [domain, path] of [['documents', '/documents'], ['datasets', '/dataset']]) {
      const response = await request.post(`/api/${domain}/tags`, { headers, data: { name: `Synthetic ${domain} images`, parent_id: null } })
      expect(response.ok(), await response.text()).toBeTruthy()
      const folder = await response.json()
      await errors.settle()
      await page.goto(path)
      await closeSidebar()
      for (const [name, mimeType, buffer] of [
        ['Synthetic large.svg', 'image/svg+xml', Buffer.from(svg)],
        ['Synthetic raster.png', 'image/png', Buffer.from(raster.split(',')[1], 'base64')],
      ]) {
        await page.getByText(folder.name, { exact: true }).click({ button: 'right' })
        await page.getByRole('menuitem', { name: /^(Modifier le dossier|Edit folder)$/, exact: true }).click()
        const trigger = page.getByRole('button', { name: new RegExp(`^(Icône du dossier|Icon for folder) ${folder.name}$`) })
        await trigger.click()
        await expect(page.getByRole('button', { name: /^(Téléverser une image|Upload an image)$/, exact: true })).toBeVisible()
        const saved = page.waitForResponse(response => response.url().endsWith(`/api/${domain}/tags/${folder.id}`) && response.request().method() === 'PUT')
        await page.locator('.tag-icon-picker input[type=file]').setInputFiles({ name, mimeType, buffer })
        const result = await saved
        expect(result.ok(), await result.text()).toBeTruthy()
        await expect(page.locator('.tag-icon-picker')).toHaveCount(0)
        await expect.poll(() => trigger.locator('img').evaluate(image => image.naturalWidth)).toBe(32)
        await errors.settle()
        await page.reload()
        await closeSidebar()
        await expect.poll(() => trigger.locator('img').evaluate(image => image.naturalWidth)).toBe(32)
      }
      await page.screenshot({ path: testInfo.outputPath(`${domain}-image-icon-${width}.png`), animations: 'disabled' })
    }
    await errors.settle()
    expect(errors()).toEqual([])
  })
}
