import { test, expect, mount, jsonRoute } from './fixtures.mjs'

test('panel states announce loading, empty and denied access and expose keyboard retry only on errors', async ({ page }) => {
  await mount(page, 'core/util/components/PanelState.vue', { props: { state: 'loading' } })
  await expect(page.getByRole('status')).toHaveAttribute('aria-busy', 'true')
  await expect(page.getByRole('status')).toContainText('Loading')
  for (const [state, message] of [['empty', 'No synthetic documents'], ['forbidden', 'Synthetic access denied']]) {
    await page.evaluate(props => window.testApp.setProps(props), { state, message })
    await expect(page.getByRole('status')).toHaveAttribute('aria-busy', 'false')
    await expect(page.getByRole('status')).toContainText(message)
    await expect(page.getByRole('button')).toHaveCount(0)
  }
  await page.evaluate(() => window.testApp.setProps({ state: 'error', message: 'Synthetic load failed', retryLabel: 'Retry' }))
  await expect(page.getByRole('alert')).toContainText('Synthetic load failed')
  await page.getByRole('button', { name: 'Retry', exact: true }).press('Enter')
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'retry').length)).toBe(1)
  await page.screenshot({ path: test.info().outputPath('panel-error.png') })
})

for (const [component, resource, emptyMessage] of [
  ['ConversationDocumentsPanel', 'documents', 'No working document is linked to the displayed messages.'],
  ['ConversationProcessesPanel', 'processes', 'No process is linked to the displayed messages.'],
  ['AgentTasksPanel', 'tasks', 'No tasks are linked to this conversation or ongoing for this agent.'],
]) {
  test(`${resource} panel keeps the retry action connected to its loader`, async ({ page }) => {
    let pending, failed = true
    await jsonRoute(page, '**/api/tasks/activity', [])
    await jsonRoute(page, '**/api/chat/recipients?*', { agents: [], users: [] })
    await page.route(`**/api/chat/rooms/synthetic-room/${resource}?*`, route => {
      if (failed) { pending = route; return }
      return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } })
    })
    await mount(page, `app/chat/components/${component}.vue`, {
      props: { roomId: 'synthetic-room', fromMessageId: 'synthetic-message', canRead: true },
      containerStyle: { height: '600px', display: 'flex', flexDirection: 'column' },
    })
    await expect.poll(() => Boolean(pending)).toBe(true)
    await expect(page.getByRole('status').filter({ hasText: 'Loading' })).toHaveAttribute('aria-busy', 'true')
    await pending.fulfill({ status: 503, json: { detail: 'Synthetic load failure' } })
    await expect(page.getByRole('alert')).toBeVisible()
    failed = false
    await page.getByRole('button', { name: 'Retry', exact: true }).press('Enter')
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(page.getByRole('status').filter({ hasText: emptyMessage })).toBeVisible()
  })
}
