import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

async function setupAdministration(page, request) {
  const pageErrors = collectPageErrors(page)
  const fixture = await (await request.post('/api/__test/seed')).json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await pageErrors.settle()
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  // Resolve optional onboarding before opening the growing agent catalogue.
  // Its locator handler would otherwise run inside the portrait assertions.
  await pageErrors.settle()
  const notificationPrompt = page.locator('.chat-notification-prompt')
  if (await notificationPrompt.isVisible()) {
    await notificationPrompt.getByRole('button', { name: 'Plus tard', exact: true }).click()
    await expect(notificationPrompt).toBeHidden()
  }
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), async prompt => {
    await prompt.getByRole('button', { name: 'Plus tard', exact: true }).click()
  })
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const prefix = `/api/__test/agent-admin/${fixture.agent_id}`
  const setup = await (await request.post(`${prefix}/setup`)).json()
  const invoke = async (name, data) => {
    const response = await request.post(`${prefix}/call/${name}`, { data })
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  return { fixture, setup, headers, prefix, invoke, pageErrors }
}

test('AgentAdmin creates an agent and generated portraits remain visible after reopening and replacement', async ({ page, request }) => {
  test.setTimeout(90_000)
  const { fixture, setup, headers, prefix, invoke, pageErrors } = await setupAdministration(page, request)
  const created = await invoke('agent_create', { configuration: {
    user_id: setup.user_id, title_id: setup.title_id,
    code: `portrait-${fixture.agent_id}`, first_name: 'Lyra', last_name: `Qualification ${fixture.agent_id}`,
    personality: '<p>Observatrice patiente.</p>', job_title: 'Astronome',
  } })
  expect(created.is_error).toBe(false)
  const target = created.data
  const errors = []
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (path.startsWith('/api/') && response.status() >= 400) errors.push(`${response.status()} ${path}`)
  })
  await pageErrors.settle()
  await page.goto('/agent')
  await expect(page.getByText(`Lyra Qualification ${fixture.agent_id}`, { exact: true })).toBeVisible()
  const portrait = page.getByRole('img', { name: `Lyra Qualification ${fixture.agent_id}`, exact: true })
  const pixel = () => portrait.evaluate(img => {
    if (!img.complete || !img.naturalWidth) return null
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 1
    const context = canvas.getContext('2d')
    context.drawImage(img, 0, 0, 1, 1)
    return [...context.getImageData(0, 0, 1, 1).data].slice(0, 3)
  })
  for (const [instructions, expected] of [['blue backdrop', [0, 0, 255]], ['green backdrop', [0, 128, 0]]]) {
    await page.locator('a[href="/params"]').first().click()
    await expect(page).toHaveURL(/\/params$/)
    const generation = await invoke('agent_avatar_generate', { agent_id: target.id, instructions })
    expect(generation.is_error).toBe(false)
    expect(generation.data.registered).toBe(true)
    expect(generation.data.status).toBe('success')
    await page.locator('a[href="/agent"]').first().click()
    await expect(portrait).toBeVisible()
    await expect.poll(() => portrait.evaluate(img => [img.naturalWidth, img.naturalHeight])).toEqual([500, 313])
    await expect.poll(async () => {
      const rgb = await pixel()
      return rgb !== null && rgb.every((value, index) => Math.abs(value - expected[index]) <= 3)
    }).toBe(true)
    await page.locator('a[href="/params"]').first().click()
    await page.locator('a[href="/agent"]').first().click()
    await expect.poll(async () => {
      const rgb = await pixel()
      return rgb !== null && rgb.every((value, index) => Math.abs(value - expected[index]) <= 3)
    }).toBe(true)
  }
  const read = await (await request.get(`/api/agents/${target.id}`, { headers })).json()
  expect(read.avatar_revision).toBe(2)
  expect(read.personality).toBe('<p>Observatrice patiente.</p>')
  await request.post(`${prefix}/revoke`)
  expect((await invoke('agent_update', { agent_id: target.id, changes: { job_title: 'Refusé' } })).is_error).toBe(true)
  expect((await (await request.get(`/api/agents/${target.id}`, { headers })).json()).job_title).toBe('Astronome')
  expect([...errors, ...pageErrors()]).toEqual([])
  expect((await request.delete(`/api/agents/${target.id}`, { headers })).status()).toBe(204)
})

test('AgentAdmin title changes refresh the reference catalogue after reopening', async ({ page, request }) => {
  test.setTimeout(90_000)
  const { fixture, headers, invoke, pageErrors } = await setupAdministration(page, request)
  // Shared references must refresh after an external administration operation.
  await page.goto('/agent')
  await page.locator('a[href="/params"]').first().click()
  const originalLabel = `Civilité synthétique ${fixture.agent_id}`
  const renamedLabel = `Civilité renommée ${fixture.agent_id}`
  const title = await invoke('agent_title_create', { configuration: { label: originalLabel, gender: 'F' } })
  expect(title.is_error).toBe(false)
  await page.locator('a[href="/agent"]').first().click()
  await page.getByRole('tab', { name: 'Civilités', exact: true }).click()
  // Browse the reference catalogue through its supported pagination controls.
  const pageSize = page.locator('.q-table__bottom .q-select')
  await pageSize.click()
  await page.getByRole('option', { name: '500', exact: true }).click()
  await expect(page.getByText(originalLabel, { exact: true })).toBeVisible()
  await page.locator('a[href="/params"]').first().click()
  expect((await invoke('agent_title_update', { title_id: title.data.id, changes: { label: renamedLabel } })).is_error).toBe(false)
  await page.locator('a[href="/agent"]').first().click()
  await page.getByRole('tab', { name: 'Civilités', exact: true }).click()
  await pageSize.click()
  await page.getByRole('option', { name: '500', exact: true }).click()
  await expect(page.getByText(renamedLabel, { exact: true })).toBeVisible()
  await expect(page.getByText(originalLabel, { exact: true })).toHaveCount(0)
  expect((await request.delete(`/api/agents/titles/${title.data.id}`, { headers })).status()).toBe(204)
  expect(pageErrors()).toEqual([])
})
