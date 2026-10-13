import { test, expect, mount, setPrivileges } from './fixtures.mjs'

const activity = { id: 'synthetic-round', status: 'RUNNING', attempt: 1,
  available_actions: ['pause', 'stop', 'respond'], control_action: null,
  response_message_id: null, message_ids: ['synthetic-input'], topic_id: null,
  effect_started: false, tools_used: [], cost: 0, execution_time: 0, process_started: false,
  created_at: '2026-01-01T10:00:00Z', finished_at: null }

test('conversation controls preserve pause, resume, stop and restart with keyboard access', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const commands = []
  let release
  let gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/chat/rooms/synthetic-room/activity/*/control', async route => {
    const body = route.request().postDataJSON()
    commands.push(body)
    await gate
    await route.fulfill({ json: { round_id: activity.id, status: 'PAUSED', control_action: null } })
  })
  await mount(page, 'app/chat/components/AgentExecutionTrace.vue', {
    props: { roomId: 'synthetic-room', activity, allowControl: true }, privileges: ['CHAT_SEND'],
  })
  const pause = page.getByRole('button', { name: 'Pause response', exact: true })
  await pause.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Stop response', exact: true })).toBeDisabled()
  expect(commands).toEqual([{ action: 'pause', expected_attempt: 1 }])
  release()
  await expect(pause).toBeEnabled()
  gate = Promise.resolve()
  await page.evaluate(activity => window.testApp.setProps({ activity: {
    ...activity, status: 'PAUSED', available_actions: ['resume', 'stop', 'respond'],
  } }), activity)
  await expect(page.getByText('Response paused', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Resume response', exact: true }).click()
  await expect.poll(() => commands.length).toBe(2)
  await page.evaluate(activity => window.testApp.setProps({ activity: { ...activity, attempt: 2 } }), activity)
  await page.getByRole('button', { name: 'Stop response', exact: true }).click()
  await expect.poll(() => commands.length).toBe(3)
  await page.evaluate(activity => window.testApp.setProps({ activity: {
    ...activity, status: 'CANCELLED', attempt: 2, available_actions: ['restart'],
  } }), activity)
  await expect(page.getByText('Response stopped', { exact: true })).toBeVisible()
  await page.screenshot({ path: '/artifacts/conversation-stopped-mobile.png' })
  await page.getByRole('button', { name: 'Restart response', exact: true }).click()
  await expect.poll(() => commands.length).toBe(4)
  expect(commands.at(-1)).toEqual({ action: 'restart', expected_attempt: 2 })
})

test('reply now errors remain retryable and late replies do not alter another conversation', async ({ page }) => {
  const commands = []
  await page.route('**/api/chat/rooms/synthetic-room/activity/*/control', async route => {
    commands.push(route.request().postDataJSON())
    await route.fulfill({ status: 409, json: { detail: 'A newer message is waiting.' } })
  })
  await mount(page, 'app/chat/components/AgentExecutionTrace.vue', {
    props: { roomId: 'synthetic-room', activity, allowControl: true }, privileges: ['CHAT_SEND'],
  })
  const reply = page.getByRole('button', { name: 'Reply now', exact: true })
  await reply.click()
  await expect(page.getByRole('alert')).toContainText('A newer message is waiting.')
  await expect(reply).toBeEnabled()
  await reply.click()
  await expect.poll(() => commands.length).toBe(2)
  await setPrivileges(page, [])
  await expect(reply).toHaveCount(0)
  await setPrivileges(page, ['CHAT_SEND'])
  let release
  await page.route('**/api/chat/rooms/synthetic-room/activity/*/control', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ status: 409, json: { detail: 'Old conversation error' } })
  })
  await reply.click()
  await expect(reply).toBeDisabled()
  await page.evaluate(activity => window.testApp.setProps({ roomId: 'other-room',
    activity: { ...activity, id: 'other-round' } }), activity)
  release()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(reply).toBeEnabled()
})
