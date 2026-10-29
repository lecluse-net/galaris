import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

for (const scenario of [
  { name: 'approve creation and background update', create: true, update: true, width: 1440 },
  { name: 'deny creation', create: false, update: false, width: 390 },
  { name: 'approve creation then deny background update', create: true, update: false, width: 390 },
]) {
  test(`document authorization: ${scenario.name}`, async ({ page, request }, testInfo) => {
    test.setTimeout(120_000)
    await page.setViewportSize({ width: scenario.width, height: 1000 })
    const errors = collectPageErrors(page)
    const seeded = await request.post('/api/__test/seed?mode=document-authorization')
    expect(seeded.ok(), await seeded.text()).toBeTruthy()
    const fixture = await seeded.json()
    const read = async () => {
      const response = await request.get(`/api/__test/document-authorization/${fixture.agent_id}`)
      expect(response.ok(), await response.text()).toBeTruthy()
      return response.json()
    }
    try {
      const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
      await page.goto('/user/login')
      await refresh
      await page.locator('input[type=email]').fill(fixture.email)
      await page.locator('input[type=password]').fill(fixture.password)
      await page.locator('button[type=submit]').click()
      await expect(page.locator('input[type=password]')).toHaveCount(0)
      await page.goto(`/chat?room=${fixture.rooms[0]}`)
      await page.locator('.composer-fields textarea').fill('Crée un document de synthèse, puis lance une tâche de fond pour le compléter en conservant le contenu initial.')
      await page.locator('.composer-fields textarea').press('Enter')
      await expect.poll(async () => (await read()).approvals.map(row => [row.function, row.status])).toEqual([['file_create', 'pending']])
      expect((await read()).documents).toEqual([])
      expect((await read()).tasks).toEqual([])

      // Reopening must restore the persisted question; it cannot require a live model request.
      await page.reload()
      const choose = async allowed => {
        const action = page.getByRole('button', { name: allowed ? 'Autoriser cette action' : 'Refuser cette action', exact: true, disabled: false })
        await expect(action).toBeEnabled()
        const answered = page.waitForResponse(response => response.request().method() === 'POST'
          && /\/interactions\/[^/]+\/answer$/.test(new URL(response.url()).pathname))
        await action.focus()
        await page.keyboard.press('Enter')
        expect((await answered).ok()).toBeTruthy()
      }
      const callsBefore = (await read()).calls.length
      await expect(page.getByRole('button', { name: 'Autoriser cette action', exact: true })).toBeEnabled()
      expect((await read()).calls).toHaveLength(callsBefore)
      await choose(scenario.create)
      if (!scenario.create) {
        await expect(page.locator('.message-timeline')).toContainText('Action interdite')
        const state = await read()
        expect(state.documents).toEqual([])
        expect(state.tasks).toEqual([])
        expect(state.approvals.map(row => row.status)).toEqual(['denied'])
      } else {
        await expect.poll(async () => (await read()).approvals.map(row => [row.function, row.status]), { timeout: 40_000 })
          .toEqual([['file_create', 'completed'], ['file_write', 'pending']])
        const waiting = await read()
        expect(waiting.documents).toHaveLength(1)
        expect(waiting.documents[0].revision).toBe(1)
        expect(waiting.documents[0].content).toContain('Initial content preserved.')
        expect(waiting.documents[0].content).not.toContain('Background task contribution.')
        expect(waiting.tasks).toHaveLength(1)
        expect(waiting.tasks[0].paused).toBe(true)
        expect(waiting.tasks[0].lease).toBeNull()
        expect(waiting.attempts.some(attempt => attempt.status === 'WAITING_APPROVAL' && attempt.finished)).toBe(true)
        expect(waiting.approvals[1].context).toBe(`task:${waiting.tasks[0].uri.split('/').at(-1)}`)
        await page.reload()
        const pending = page.locator('.interaction-choice').filter({ has: page.getByRole('button', {
          name: 'Autoriser cette action', exact: true, disabled: false,
        }) })
        await expect(pending).toHaveCount(1)
        await expect(pending).toContainText('Background task contribution.')
        await page.screenshot({ path: testInfo.outputPath('document-update-awaiting-consent.png'), fullPage: true })
        await choose(scenario.update)
        await expect.poll(async () => (await read()).tasks[0]?.status, { timeout: 40_000 }).toMatch(/SUCCESS|ERROR/)
        const final = await read()
        expect(final.documents).toHaveLength(1)
        expect(final.documents[0].uri).toBe(waiting.documents[0].uri)
        expect(final.documents[0].revision).toBe(scenario.update ? 2 : 1)
        expect(final.documents[0].content.includes('Background task contribution.')).toBe(scenario.update)
        expect(final.documents[0].content).toContain('Initial content preserved.')
        expect(final.revisions.sort()).toEqual(scenario.update ? [1, 2] : [1])
        expect(final.approvals.map(row => row.status)).toEqual(['completed', scenario.update ? 'completed' : 'denied'])
        expect(final.tasks).toHaveLength(1)
        expect(final.tasks[0].paused).toBe(false)
        expect(final.tasks[0].lease).toBeNull()
        expect(final.tasks[0].data.authorization_requests ?? []).toEqual([])
        expect(final.tasks[0].result.result).toContain(scenario.update ? 'Document complété' : 'Action interdite')
        await page.reload()
        expect((await read()).documents).toEqual(final.documents)
        expect((await read()).approvals).toEqual(final.approvals)
      }
      await errors.settle()
      expect(errors()).toEqual([])
    } finally {
      const diagnostics = await request.get(`/api/__test/document-authorization/${fixture.agent_id}`)
      await testInfo.attach('document-authorization-state', {
        body: await diagnostics.text(), contentType: diagnostics.ok() ? 'application/json' : 'text/plain',
      })
    }
  })
}
