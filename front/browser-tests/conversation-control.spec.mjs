import { test, expect, mount, setPrivileges, jsonRoute } from './fixtures.mjs'

const activity = { id: 'synthetic-round', status: 'RUNNING', attempt: 1,
  available_actions: ['pause', 'stop', 'respond'], control_action: null,
  response_message_id: null, message_ids: ['synthetic-input'], topic_id: null,
  effect_started: false, tools_used: [], cost: 0, execution_time: 0, process_started: false,
  created_at: '2026-01-01T10:00:00Z', finished_at: null }

test('a remote sender identifier remains visible without a pending authorization', async ({ page }) => {
  await jsonRoute(page, '**/api/topics?*', { items: [], total: 0 })
  const message = { id: 'synthetic-input', agent_id: 7, agent_name: 'Synthetic Agent', channel_kind: 'telegram',
    payload: { text: 'Synthetic remote message', sender: { id: '424242', display_name: 'Synthetic Person' } },
    round_id: null, round_status: null, response_text: 'Synthetic answer', response_error: null,
    created_at: activity.created_at, responded_at: activity.created_at }
  await mount(page, 'app/conversation/components/ConversationRoundDetail.vue', { props: {
    message, round: null, calls: [], loading: false, error: '', callsLoading: false, callsError: '',
  } })
  await expect(page.getByText('Remote user identifier : 424242', { exact: true })).toBeVisible()
  await page.evaluate(message => window.testApp.setProps({ round: {
    id: 'synthetic-round', agent_id: 7, agent_name: 'Synthetic Agent', status: 'SUCCEEDED',
    rendered_input: [{ text: message.payload.text, sender_external_id: '424242', sender_display_name: 'Synthetic Person' }],
    response_text: 'Synthetic answer', delivery_state: 'DELIVERED', attempt_count: 1,
    created_at: message.created_at, unknown_notifications: [], contact_authorization: null,
  } }), message)
  await expect(page.getByText('Remote user identifier : 424242', { exact: true })).toBeVisible()
})

for (const width of [390, 1280]) test(`pending contact identity and permission navigation remain usable at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 844 })
  const authorization = { permission_id: 'synthetic-permission', allowed: null, manager_user_id: 7,
    external_id: '420', display_name: 'Synthetic Contact',
    profile: { username: 'synthetic_contact', language_code: 'fr', is_bot: false, is_premium: true } }
  await mount(page, 'app/conversation/components/ContactAuthorization.vue', {
    props: { authorization }, privileges: ['PERMISSION_ACCESS'],
  })
  await expect(page.getByText('Reply paused: waiting for the manager’s consent.')).toBeVisible()
  await expect(page.getByText('420', { exact: true })).toBeVisible()
  await expect(page.getByText('synthetic_contact', { exact: true })).toBeVisible()
  await expect(page.getByText('fr', { exact: true })).toBeVisible()
  const permissions = page.getByRole('link', { name: 'Open permissions' })
  await expect(permissions).toHaveAttribute('href', '/permissions')
  await permissions.focus()
  await page.screenshot({ path: `/artifacts/contact-authorization-${width}.png` })
  await setPrivileges(page, [])
  await expect(permissions).toHaveCount(0)
  await expect(page.getByText('420', { exact: true })).toBeVisible()
  await page.evaluate(authorization => window.testApp.setProps({ authorization: { ...authorization, allowed: false } }), authorization)
  await expect(page.getByText('The manager denied exchanges with this person.')).toBeVisible()
})

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

test('pause errors remain retryable and late replies do not alter another conversation', async ({ page }) => {
  const commands = []
  await page.route('**/api/chat/rooms/synthetic-room/activity/*/control', async route => {
    commands.push(route.request().postDataJSON())
    await route.fulfill({ status: 409, json: { detail: 'A newer message is waiting.' } })
  })
  await mount(page, 'app/chat/components/AgentExecutionTrace.vue', {
    props: { roomId: 'synthetic-room', activity, allowControl: true }, privileges: ['CHAT_SEND'],
  })
  const reply = page.getByRole('button', { name: 'Pause response', exact: true })
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
