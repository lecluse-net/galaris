import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const [language, width, labels] of [
  ['fr', 390, {
    title: 'Utilisateurs & Droits', roles: 'Rôles', catalogue: 'Privilèges', plugins: 'Extensions',
    category: 'Agents & équipes', privilege: 'Consulter les agents et les fonctions', admin: 'Administrateur',
  }],
  ['en', 1440, {
    title: 'Users & Permissions', roles: 'Roles', catalogue: 'Privileges', plugins: 'Plugins',
    category: 'Agents & teams', privilege: 'View agents and job titles', admin: 'Administrator',
  }],
  ['zh', 1440, {
    title: '用户与权限', roles: '角色', catalogue: '权限', plugins: '插件',
    category: '智能体与团队', privilege: '查看智能体和职务', admin: '管理员',
  }],
]) test(`roles save categorized privileges in ${language} at ${width}px`, async ({ page, request }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const checked = async response => {
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  const fixture = await checked(await request.post('/api/__test/seed'))
  const session = await checked(await request.post('/api/auth/login-json', {
    data: { email: fixture.email, password: fixture.password },
  }))
  const headers = { Authorization: `Bearer ${session.access_token}` }
  await checked(await request.put('/api/auth/me', { headers, data: { language } }))
  const categoryPath = '/api/authorize/privilege-lists'
  const categories = await checked(await request.get(categoryPath, { headers }))
  expect(categories.filter(item => item.translation_key)).toHaveLength(15)
  const plugins = categories.find(item => item.translation_key === 'authorize.privilegeLists.defaults.plugins')
  expect(plugins?.privileges.map(privilege => privilege.code).sort()).toEqual(['PLUGIN_ACCESS', 'PLUGIN_EDIT'])
  expect(categories.some(item => item.display_name === 'Chat')).toBe(false)
  const key = 'authorize.privilegeLists.defaults.agentsTeams'
  const installed = categories.find(item => item.translation_key === key)
  expect(installed.display_name).toBe(key)
  const privilege = installed.privileges.find(item => item.code === 'AGENT_ACCESS')
  expect(privilege).toBeDefined()

  // Category administration is exposed in the dev-only panel. Exercise storage
  // against the real API here and the editing flow in the component suite.
  const unchanged = await checked(await request.put(`${categoryPath}/${installed.id}`, {
    headers, data: { display_name: key },
  }))
  expect(unchanged).toMatchObject({ display_name: key, translation_key: key })
  const custom = await checked(await request.post(categoryPath, {
    headers, data: { display_name: `Synthetic category ${fixture.agent_id}` },
  }))
  const persisted = await checked(await request.get(categoryPath, { headers }))
  expect(persisted.find(item => item.id === custom.id)).toMatchObject({
    display_name: custom.display_name, translation_key: null,
  })

  const roleName = `Synthetic role ${fixture.agent_id}`
  const role = await checked(await request.post('/api/authorize/roles', {
    headers, data: { code: `synthetic-role-${fixture.agent_id}`, display_name: roleName },
  }))

  const errors = collectPageErrors(page)
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  await page.locator('button[type=submit]').click()
  await expect(page.locator('.user-menu-wrapper').first()).toBeVisible()
  await expect(page).toHaveURL(/\/$/)
  await page.goto('/authorize')
  await expect(page).toHaveURL(/\/users\?tab=roles$/)
  await expect(page.getByRole('heading', { name: labels.title, exact: true })).toBeVisible()
  if (width < 1024) await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), async backdrop => {
    await backdrop.click({ position: { x: width - 10, y: 200 } })
  })
  const roleButton = page.getByRole('button', { name: roleName, exact: true })
  const selectRole = () => roleButton.click()
  const category = page.locator('section').filter({ has: page.getByRole('heading', { name: labels.category, exact: true }) })
  const toggle = category.getByRole('switch', { name: labels.privilege, exact: true })
  const rolePath = `/api/authorize/roles/${role.id}`
  const waitForWrite = method => page.waitForResponse(response =>
    response.url().endsWith(`${rolePath}/privileges`) && response.request().method() === method)

  await expect(page.getByRole('tab', { name: labels.roles, exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: labels.catalogue, exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: labels.plugins, exact: true })).toBeVisible()
  await page.getByRole('button', { name: labels.admin, exact: true }).click()
  const adminCatalogue = page.getByRole('region', { name: new RegExp(labels.admin) })
  await expect(adminCatalogue.getByText(labels.privilege, { exact: true })).toBeAttached()
  await expect(adminCatalogue.getByRole('switch')).toHaveCount(0)
  await selectRole()
  await expect(toggle).not.toBeChecked()
  const catalogue = page.getByRole('region', { name: new RegExp(roleName) })
  const title = page.getByRole('heading', { level: 1 })
  const titleTop = (await title.boundingBox()).y
  const roleTop = (await roleButton.boundingBox()).y
  await catalogue.press('End')
  await expect.poll(() => catalogue.evaluate(element => element.scrollTop)).toBeGreaterThan(0)
  expect((await title.boundingBox()).y).toBe(titleTop)
  expect((await roleButton.boundingBox()).y).toBe(roleTop)
  const grant = waitForWrite('POST')
  await category.getByText(labels.privilege, { exact: true }).click()
  expect((await checked(await grant)).privileges.map(item => item.id)).toEqual([privilege.id])
  await expect(toggle).toBeChecked()

  await page.reload()
  await selectRole()
  await expect(toggle).toBeChecked()
  await page.screenshot({ path: testInfo.outputPath('role-privileges.png') })
  const revoke = waitForWrite('DELETE')
  await toggle.press('Space')
  expect((await checked(await revoke)).privileges).toEqual([])
  await expect(toggle).not.toBeChecked()
  expect((await checked(await request.get(rolePath, { headers }))).privileges).toEqual([])

  await errors.settle()
  expect(errors()).toEqual([])
})
