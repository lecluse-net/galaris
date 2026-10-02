import { randomUUID } from 'node:crypto'
import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const width of [390, 1440]) {
  test(`human approval protects the exact action and survives reopening at ${width}px`, async ({ page, request }) => {
    test.setTimeout(90_000)
    await page.setViewportSize({ width, height: 900 })
    const errors = collectPageErrors(page)
    const fixture = await (await request.post('/api/__test/seed')).json()
    const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
    await page.goto('/user/login')
    await refresh
    await page.locator('input[type=email]').fill(fixture.email)
    await page.locator('input[type=password]').fill(fixture.password)
    const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
    await page.locator('button[type=submit]').click()
    const session = await (await login).json()
    const headers = { Authorization: `Bearer ${session.access_token}` }
    const prefix = `/api/__test/agent-admin/${fixture.agent_id}`
    const setup = await (await request.post(`${prefix}/setup`)).json()
    const setMode = state => request.put(`/api/connections/${setup.connection_id}/functions/agent_update`, { headers, data: { state } })
    expect((await setMode('ask')).ok()).toBeTruthy()
    const read = async () => (await request.get(`/api/agents/${fixture.agent_id}`, { headers })).json()
    const original = await read()
    const invoke = async (operation, title, continuation) => {
      const query = new URLSearchParams({ operation_id: operation })
      if (continuation) query.set('continuation', continuation)
      const response = await request.post(`${prefix}/call/agent_update?${query}`, {
        data: { agent_id: fixture.agent_id, changes: { job_title: title } },
      })
      expect(response.ok(), await response.text()).toBeTruthy()
      return response.json()
    }
    for (const allowed of [false, true]) {
      const operation = randomUUID()
      const title = `Synthetic ${allowed ? 'approved' : 'denied'} ${fixture.agent_id}`
      const pending = await invoke(operation, title)
      const control = pending.meta['galaris.authorization/v1']
      expect(control.disposition).toBe('authorization_required')
      expect((await read()).job_title).toBe(original.job_title)
      const path = `/connection/permissions?request=${control.request_id}`
      await errors.settle()
      await page.goto(path)
      await expect(page.getByRole('dialog')).toContainText(title)
      await page.keyboard.press('Escape')
      await expect(page.getByRole('dialog')).toHaveCount(0)
      await errors.settle()
      await page.goto('/agent')
      await expect(page.getByText(`${original.first_name} ${original.last_name}`, { exact: true })).toBeVisible()
      await errors.settle()
      await page.goto(path)
      const dialog = page.getByRole('dialog')
      const answer = page.waitForResponse(response => response.url().endsWith(`/action-authorizations/${control.request_id}/answer`))
      await dialog.getByRole('button', { name: allowed ? 'Autoriser cette action' : 'Refuser cette action', exact: true }).focus()
      await page.keyboard.press('Enter')
      expect((await answer).ok()).toBeTruthy()
      await expect(dialog.getByRole('button', { name: 'Autoriser cette action', exact: true })).toHaveCount(0)
      const continued = await invoke(operation, title, control.continuation)
      expect(continued.is_error).toBe(!allowed)
      expect((await read()).job_title).toBe(allowed ? title : original.job_title)
      const replay = await invoke(operation, title, control.continuation)
      expect(replay.is_error).toBe(true)
      expect(replay.meta['galaris.authorization/v1'].status).toBe(allowed ? 'completed' : 'denied')
    }
    expect((await setMode('disabled')).ok()).toBeTruthy()
    expect((await invoke(randomUUID(), 'Blocked synthetic mutation')).is_error).toBe(true)
    expect((await read()).job_title).toBe(`Synthetic approved ${fixture.agent_id}`)
    await errors.settle()
    await page.goto(`/agent?agent_id=${fixture.agent_id}`)
    const toggle = page.getByRole('switch', { name: /Mode YOLO/ })
    await expect(toggle).toHaveAttribute('aria-checked', 'false')
    await toggle.click()
    const warning = page.getByRole('dialog').filter({ hasText: 'Danger :' })
    await expect(warning).toContainText('sans vous demander confirmation')
    await warning.getByRole('button', { name: 'Annuler', exact: true }).click()
    expect((await read()).yolo).toBe(false)
    await toggle.click()
    const activate = page.waitForResponse(response => response.url().endsWith(`/agents/${fixture.agent_id}/yolo`))
    await warning.getByRole('button', { name: 'Activer YOLO', exact: true }).click()
    expect((await activate).ok()).toBeTruthy()
    await expect(toggle).toHaveAttribute('aria-checked', 'true')
    expect((await invoke(randomUUID(), 'YOLO blocked synthetic mutation')).is_error).toBe(true)
    expect((await setMode('ask')).ok()).toBeTruthy()
    expect((await invoke(randomUUID(), 'YOLO approved synthetic mutation')).is_error).toBe(false)
    const audit = await (await request.get(`/api/tools/action-authorizations?agent_id=${fixture.agent_id}`, { headers })).json()
    expect(audit.items).toEqual(expect.arrayContaining([expect.objectContaining({ status: 'completed', decision_source: 'agent_yolo' })]))
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-checked', 'false')
    const waiting = await invoke(randomUUID(), 'Human approval restored')
    expect(waiting.meta['galaris.authorization/v1'].disposition).toBe('authorization_required')
    expect((await read()).job_title).toBe('YOLO approved synthetic mutation')
    expect(errors()).toEqual([])
  })
}
