import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

const room = '00000000-0000-4000-8000-000000000101'
const message = '00000000-0000-4000-8000-000000000102'
const document = '00000000-0000-4000-8000-000000000103'
const task = '00000000-0000-4000-8000-000000000104'

test('first mission retries the same message, restores progress and requires a saved document for completion', async ({ page }, testInfo) => {
  await jsonRoute(page, '**/api/chat/status', { enabled: true, chat_enabled: true })
  await jsonRoute(page, '**/api/chat/recipients?*', { agents: [{ agent_id: 7, display_name: 'Alice Example', active: true }] })
  let creations = 0, failSend = true, finished = false, saved = false
  const clients = []
  await page.route('**/api/chat/rooms', route => { creations++; return route.fulfill({ json: { id: room } }) })
  await page.route(`**/api/chat/rooms/${room}/messages`, route => {
    const payload = route.request().postDataJSON(); clients.push(payload.client_message_id)
    expect(payload.task_requested).toBe(true)
    return failSend ? route.fulfill({ status: 503, json: { detail: 'Synthetic uncertain delivery' } }) : route.fulfill({ json: { id: message } })
  })
  await page.route(`**/api/chat/rooms/${room}/tasks?*`, route => route.fulfill({ json: { items: finished ? [{ id: task, label: 'First mission', status: 'SUCCESS', paused: false }] : [], total: finished ? 1 : 0 } }))
  await page.route(`**/api/chat/rooms/${room}/documents?*`, route => route.fulfill({ json: { items: saved ? [{ id: document, label: 'Workshop summary', uri: `document://${document}` }] : [], total: saved ? 1 : 0 } }))
  const missionPrivileges = ['CHAT_ACCESS', 'CHAT_MANAGE', 'CHAT_SEND', 'TASK_ACCESS', 'DOCUMENT_ACCESS']
  await mount(page, 'app/onboarding/components/FirstMission.vue', { privileges: missionPrivileges })
  await expect(page.getByRole('textbox', { name: 'Request to delegate' })).not.toBeEmpty()
  await page.getByRole('button', { name: 'Start mission', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  failSend = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Mission in progress')
  expect(creations).toBe(1)
  expect(clients).toHaveLength(2)
  expect(clients[0]).toBe(clients[1])
  finished = true
  await page.getByRole('button', { name: 'Refresh progress', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('no associated document')
  saved = true
  await page.getByRole('button', { name: 'Refresh progress', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Workshop summary', exact: true })).toHaveAttribute('href', `/documents?document_id=${document}`)
  await expect(page.getByRole('status')).toContainText('document is available')
  await page.screenshot({ path: testInfo.outputPath('first-mission-complete.png') })
  await mount(page, 'app/onboarding/components/FirstMission.vue', { privileges: missionPrivileges })
  await expect(page.getByRole('link', { name: 'Workshop summary', exact: true })).toBeVisible()
  expect(creations).toBe(1)
})

test('first mission explains missing permissions before making any request', async ({ page }) => {
  await mount(page, 'app/onboarding/components/FirstMission.vue', { privileges: ['CHAT_ACCESS'] })
  await expect(page.getByText('This journey requires Discussion access', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start mission' })).toHaveCount(0)
})

test('a role change during room creation prevents a late mission send', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/status', { enabled: true, chat_enabled: true })
  await jsonRoute(page, '**/api/chat/recipients?*', { agents: [{ agent_id: 7, display_name: 'Alice Example', active: true }] })
  let release, sends = 0
  await page.route('**/api/chat/rooms', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { id: room } })
  })
  await page.route(`**/api/chat/rooms/${room}/messages`, route => { sends++; return route.fulfill({ json: { id: message } }) })
  await mount(page, 'app/onboarding/components/FirstMission.vue', { privileges: ['CHAT_ACCESS', 'CHAT_MANAGE', 'CHAT_SEND', 'TASK_ACCESS', 'DOCUMENT_ACCESS'] })
  await expect(page.getByRole('button', { name: 'Start mission', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Start mission', exact: true }).click()
  await expect.poll(() => Boolean(release)).toBe(true)
  await setPrivileges(page, ['CHAT_ACCESS'])
  release()
  await expect(page.getByText('This journey requires Discussion access', { exact: false })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open discussion' })).toHaveCount(0)
  expect(sends).toBe(0)
})

test('memory decisions display enrichment and contradictions with their content and target', async ({ page }) => {
  await mount(page, 'app/lab/components/MemoryExtractionDecisionPreview.vue', { props: {
    input: { existing_memories: [{ id: 'synthetic-memory', title: 'Workshop policy' }] },
    value: { operations: [
      { action: 'ENRICH', target_memory_id: 'synthetic-memory', content: 'Cameras may be borrowed.' },
      { action: 'CONTRADICT', target_memory_id: 'synthetic-memory', content: 'Only experienced participants may join.' },
    ] },
  } })
  await expect(page.getByText('ENRICH', { exact: true })).toBeVisible()
  await expect(page.getByText('CONTRADICT', { exact: true })).toBeVisible()
  await expect(page.getByText('Cameras may be borrowed.', { exact: true })).toBeVisible()
  await expect(page.getByText('Workshop policy', { exact: true })).toHaveCount(2)
})
