import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document as documentFixture } from './data.mjs'

const events = (page, name) => page.evaluate(name => window.testApp.events.filter(event => event.name === name).map(event => name === 'send' ? event.args.slice(0, 4) : event.args), name)
const acknowledgeSend = page => page.evaluate(() => window.testApp.events.filter(event => event.name === 'send').at(-1).args[4](true))

for (const suggestedLabel of ['Alice', 'Alice (3)']) {
test(`room creation uses the available name ${suggestedLabel} and preserves custom names and preferences`, async ({ page }) => {
  await jsonRoute(page, '**/api/agents/selection?scope=dialogue', [{ id: 7, label: 'Alice', has_avatar: false }])
  await page.route('**/api/chat/agents/7/avatar', route => route.fulfill({ status: 404, body: '' }))
  await mount(page, 'app/chat/components/RoomCreateDialog.vue', { props: { modelValue: true, agents: [{ agent_id: 7, display_name: 'Alice', suggested_room_label: suggestedLabel, has_avatar: false }] } })
  const create = page.getByRole('button', { name: 'Chat', exact: true })
  await expect(create).toBeDisabled()
  await page.getByRole('combobox', { name: 'Agent', exact: true }).click()
  await page.getByRole('option', { name: 'Alice' }).click()
  const label = page.getByRole('textbox', { name: 'Conversation name', exact: true })
  await expect(label).toHaveValue(suggestedLabel)
  await label.fill('   ')
  await expect(create).toBeDisabled()
  await label.fill('  Private conversation  ')
  await page.getByRole('switch').click()
  await expect(page.locator('.dream-topic-hint')).toBeVisible()
  await create.click()
  await expect.poll(() => events(page, 'create')).toEqual([[7, 'Private conversation', null, false]])
  await expect(page.getByRole('combobox')).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'Create a thematic dossier', exact: true })).toHaveCount(0)
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
}

test('room creation can create and select a topic while preserving conversation preferences', async ({ page }) => {
  const topic = { id: 'new-topic', title: 'New subject', description: '', keywords: [], revision: 1 }
  const created = []
  await jsonRoute(page, '**/api/agents/selection?scope=dialogue', [{ id: 7, label: 'Alice', has_avatar: false }])
  await jsonRoute(page, '**/api/topics/keywords', [])
  await jsonRoute(page, '**/api/topics/new-topic', topic)
  await page.route('**/api/topics', async route => {
    created.push(route.request().postDataJSON())
    await route.fulfill({ status: 201, json: topic })
  })
  await page.route('**/api/chat/agents/7/avatar', route => route.fulfill({ status: 404, body: '' }))
  await mount(page, 'app/chat/components/RoomCreateDialog.vue', { privileges: ['TOPIC_EDIT', 'AGENT_MANAGE_ALL'], props: {
    modelValue: true, canEditTopic: true, agents: [{ agent_id: 7, display_name: 'Alice', has_avatar: false }],
  } })
  await page.getByRole('combobox', { name: 'Agent', exact: true }).click()
  await page.getByRole('option', { name: 'Alice' }).click()
  await page.getByRole('textbox', { name: 'Conversation name', exact: true }).fill('Private conversation')
  await page.getByRole('switch').click()
  await page.getByRole('button', { name: 'Create a thematic dossier', exact: true }).click()
  const topicForm = page.getByRole('dialog').last()
  await topicForm.getByRole('textbox', { name: 'Dossier', exact: true }).fill('  New subject  ')
  await topicForm.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await expect(page.getByText('New subject', { exact: true })).toBeVisible()
  expect(created).toEqual([{ title: 'New subject', description: '', keywords: [] }])
  await expect(page.locator('.dream-topic-hint')).toHaveCount(0)
  await page.getByRole('button', { name: 'Chat', exact: true }).click()
  await expect.poll(() => events(page, 'create')).toEqual([[7, 'Private conversation', 'new-topic', false]])
})

test('cancelling or failing topic creation preserves the existing conversation topic', async ({ page }) => {
  await jsonRoute(page, '**/api/topics?*', { items: [{ id: 'existing', title: 'Existing subject' }], total: 1 })
  await jsonRoute(page, '**/api/topics/keywords', [])
  await page.route('**/api/topics', route => route.fulfill({ status: 503, json: { detail: 'Unavailable' } }))
  await mount(page, 'app/chat/components/RoomCreateDialog.vue', { privileges: ['TOPIC_EDIT', 'AGENT_MANAGE_ALL'], props: {
    modelValue: true, canEditTopic: true, agents: [],
  } })
  await page.getByRole('combobox', { name: 'Default topic', exact: true }).click()
  await page.getByRole('option', { name: 'Existing subject' }).click()
  await page.getByRole('button', { name: 'Create a thematic dossier', exact: true }).click()
  const topicForm = page.getByRole('dialog').last()
  await topicForm.getByRole('textbox', { name: 'Dossier', exact: true }).fill('Unsuccessful subject')
  await topicForm.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('The dossier operation failed.', { exact: true })).toBeVisible()
  await expect(topicForm.getByRole('textbox', { name: 'Dossier', exact: true })).toHaveValue('Unsuccessful subject')
  await page.locator('.q-dialog__backdrop').last().click({ position: { x: 3, y: 3 } })
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await expect(page.getByText('Existing subject', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Create a thematic dossier', exact: true }).click()
  await expect(topicForm.getByRole('textbox', { name: 'Dossier', exact: true })).toHaveValue('')
  await topicForm.getByRole('button', { name: 'Cancel', exact: true }).last().click()
  await expect(page.getByText('Existing subject', { exact: true })).toBeVisible()
})

test('room preferences emit archive and restore for the displayed room', async ({ page }) => {
  const room = { id: 'room-a', label: 'Example', archived: false, show_last_message: true, topic_id: null }
  await mount(page, 'app/chat/components/RoomPreferencesDialog.vue', { props: { modelValue: true, room } })
  await page.getByRole('button', { name: /archive/i }).click()
  await expect.poll(() => events(page, 'archive')).toEqual([[true]])
  await page.evaluate(room => window.testApp.setProps({ room: { ...room, archived: true } }), room)
  await page.getByRole('button', { name: /restore|unarchive/i }).click()
  await expect.poll(() => events(page, 'archive')).toEqual([[true], [false]])
})

test('composer sends task intent and the selected effort then resets', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  await mount(page, 'app/chat/components/Composer.vue', { props: { roomId: 'room-a', sending: false, commands: ['task', 'effort', 'plan'] } })
  const input = page.locator('textarea')
  await input.fill('@effort Analyse the report')
  const slider = page.getByRole('slider')
  await expect(slider).toBeVisible()
  const bounds = await slider.boundingBox()
  await slider.click({ position: { x: bounds.width - 2, y: bounds.height / 2 } })
  await expect(slider).toHaveAttribute('aria-valuenow', '5')
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => events(page, 'send')).toEqual([['@effort Analyse the report', undefined, 'max', true]])
  await expect(input).toHaveValue('@effort Analyse the report')
  await acknowledgeSend(page)
  await expect(input).toHaveValue('')
  await expect(slider).toHaveCount(0)
  await input.fill('Ordinary message')
  await input.press('Enter')
  await expect.poll(() => events(page, 'send')).toHaveLength(2)
  expect((await events(page, 'send'))[1]).toEqual(['Ordinary message', undefined, undefined, false])
  await acknowledgeSend(page)
})

for (const width of [390, 1280]) {
  test(`composer Post button handles empty drafts, attachments and sending at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
    await mount(page, 'app/chat/components/Composer.vue', { props: { roomId: 'room-a', sending: false, commands: ['task'] } })
    const input = page.locator('textarea')
    const post = page.getByRole('button', { name: 'Post', exact: true })
    await expect(post).toBeVisible()
    await expect(post).toBeDisabled()
    await input.fill('   ')
    await expect(post).toBeDisabled()
    await input.fill('First line\nSecond line\nThird line')
    await expect(post).toBeEnabled()
    const message = 'First line\nSecond line\nThird line\nFourth line\nFifth line\nLast line'
    await input.fill(`  ${message}  `)
    await post.click()
    await expect.poll(() => events(page, 'send')).toEqual([[message, undefined, undefined, false]])
    await acknowledgeSend(page)
    await expect(input).toHaveValue('')
    await expect(post).toBeDisabled()

    await page.locator('input[type=file]').setInputFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('Notes') })
    await expect(page.getByRole('button', { name: 'Remove notes.txt', exact: true })).toBeVisible()
    await expect(post).toBeEnabled()
    const upload = page.getByRole('button', { name: 'Add attachments', exact: true })
    const nextFile = page.waitForEvent('filechooser')
    await upload.click()
    if (width < 1024) await page.getByText('From device', { exact: true }).click()
    await (await nextFile).setFiles({ name: 'extra.txt', mimeType: 'text/plain', buffer: Buffer.from('Extra') })
    await expect(page.getByRole('button', { name: 'Remove extra.txt', exact: true })).toBeVisible()
    await page.evaluate(() => window.testApp.setProps({ sending: true }))
    await expect(post).toBeDisabled()
    await input.press('Enter')
    await expect.poll(() => events(page, 'send')).toHaveLength(1)
    await page.evaluate(() => window.testApp.setProps({ sending: false }))
    await post.click()
    await expect.poll(() => page.evaluate(() => {
      const sent = window.testApp.events.filter(event => event.name === 'send').at(-1)
      return [sent.args[0], sent.args[1]?.map(file => [file.name, file.type, file.size])]
    })).toEqual(['', [['notes.txt', 'text/plain', 5], ['extra.txt', 'text/plain', 5]]])
    expect(await page.evaluate(async () => {
      const sent = window.testApp.events.filter(event => event.name === 'send').at(-1)
      return Promise.all(sent.args[1].map(file => file.text()))
    })).toEqual(['Notes', 'Extra'])
    await acknowledgeSend(page)
    await expect(post).toBeDisabled()
  })
}

test('conversation process states and opening details follow the loaded data', async ({ page }) => {
  const run = { id: 'process-a', tool_code: 'n8n', process_label: 'Synthetic image export', summary: 'Synthetic image export',
    status: 'running', input: { format: 'png' }, output: null, engine_metadata: {},
    error_message: null, created_at: '2026-09-01T12:00:00Z', task_ids: [], events: [], llm_calls: [] }
  await jsonRoute(page, '**/api/chat/rooms/room-a/processes?*', { items: [run], total: 1 })
  let reads = 0
  await page.route('**/api/processes/runs/process-a', route => { reads++; return route.fulfill({ json: run }) })
  await mount(page, 'app/chat/components/ConversationProcessesPanel.vue', { props: { roomId: 'room-a', fromMessageId: 'message-a', canRead: true }, privileges: ['PROCESS_READ'] })
  await expect(page.locator('.q-item .q-spinner').first()).toBeVisible()
  await page.locator('.q-item').first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.locator('textarea.code-editor').first()).toHaveValue(/png/)
  run.status = 'success'; run.output = { result: 'Synthetic completed export' }
  await page.evaluate(() => window.testApp.emitSocket('process_run.update', { data: { id: 'process-a' } }))
  await expect(page.getByRole('textbox', { name: 'Output', exact: true })).toHaveValue(/Synthetic completed export/)
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true })).toHaveCount(0)
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Delete run', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const afterClose = reads
  await page.evaluate(() => window.testApp.emitSocket('process_run.update', { data: { id: 'process-a' } }))
  await page.waitForTimeout(200)
  expect(reads).toBe(afterClose)
  await page.locator('.q-item').first().click()
  await expect(page.getByRole('textbox', { name: 'Output', exact: true })).toHaveValue(/Synthetic completed export/)
})

for (const width of [390, 1280]) test(`conversation processes place recent runs at the bottom and follow new runs at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  const runs = Array.from({ length: 56 }, (_, index) => ({
    id: `process-${String(index + 1).padStart(3, '0')}`, process_label: `Synthetic run ${String(index + 1).padStart(3, '0')}`,
    tool_code: 'n8n', status: 'success', created_at: new Date(Date.UTC(2026, 8, 1, 12, 0, index)).toISOString(),
  })).reverse()
  let reads = 0
  await page.route('**/api/chat/rooms/room-a/processes?*', route => {
    reads++
    const query = new URL(route.request().url()).searchParams
    const size = Number(query.get('page_size')), pageNumber = Number(query.get('page'))
    expect(size).toBeLessThanOrEqual(500)
    if (pageNumber > 1) expect(size).toBe(50)
    return route.fulfill({ json: { items: runs.slice((pageNumber - 1) * size, pageNumber * size), total: runs.length } })
  })
  await mount(page, 'app/chat/components/ConversationProcessesPanel.vue', {
    props: { roomId: 'room-a', fromMessageId: 'message-a', canRead: true },
    containerStyle: { height: '100vh', display: 'flex', flexDirection: 'column' },
  })
  const list = page.locator('.conversation-work-list')
  const labels = list.locator('.text-weight-medium')
  const atBottom = () => list.evaluate(element => element.scrollHeight - element.clientHeight - element.scrollTop < 2)
  await expect(labels).toHaveCount(50)
  await expect(labels.first()).toHaveText('Synthetic run 007')
  await expect(labels.last()).toHaveText('Synthetic run 056')
  await expect.poll(atBottom).toBe(true)
  await list.evaluate(element => { element.scrollTop = 0 })
  await expect(labels).toHaveCount(56)
  await expect(labels.first()).toHaveText('Synthetic run 001')
  await expect(list.getByText('Synthetic run 007', { exact: true })).toBeInViewport()
  await list.evaluate(element => { element.scrollTop = 0 })
  const beforeUpdate = reads
  runs[0].status = 'running'
  await page.evaluate(() => window.testApp.emitSocket('process_run.update', { data: { id: 'process-056' } }))
  await expect.poll(() => reads).toBeGreaterThan(beforeUpdate)
  await expect.poll(() => list.evaluate(element => element.scrollTop)).toBe(0)
  runs.unshift({ ...runs[0], id: 'process-057', process_label: 'Synthetic run 057', created_at: '2026-09-01T12:01:00Z' })
  await page.evaluate(() => window.testApp.emitSocket('process_run.create', { data: { id: 'process-057' } }))
  await expect(labels.last()).toHaveText('Synthetic run 057')
  await expect.poll(atBottom).toBe(true)
  await expect(list.getByText('Synthetic run 057', { exact: true })).toBeInViewport()
})

test('conversation documents hide UUID labels and respect read and edit permissions', async ({ page }) => {
  await jsonRoute(page, '**/api/documents/doc-a?agent_id=7', { item: { ...documentFixture, payload: { text: '<p>Working document</p>' } }, agent_id: 7 })
  await jsonRoute(page, '**/api/chat/rooms/room-a/documents?*', { items: [{ id: 'doc-a', label: '12345678-1234-1234-8234-123456789abc', revision: 2, updated_at: null }], total: 1 })
  await mount(page, 'app/chat/components/ConversationDocumentsPanel.vue', { props: { roomId: 'room-a', fromMessageId: 'message-a', conversationAgentId: 7, canRead: true, canEdit: false } })
  await expect(page.locator('.conversation-work-list')).not.toContainText('12345678')
  await expect(page.locator('.conversation-work-list')).toContainText('Working document')
  await expect(page.locator('.conversation-documents-toolbar button')).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ canEdit: true }))
  await expect(page.locator('.conversation-documents-toolbar button')).toHaveCount(1)
  await page.evaluate(() => window.testApp.setProps({ canRead: false }))
  await expect(page.locator('.conversation-work-list')).toHaveCount(0)
})

test('conversation viewer always keeps a person selected and can return to myself', async ({ page }) => {
  await page.route('**/api/chat/agents/7/avatar', route => route.fulfill({ status: 404, body: '' }))
  await mount(page, 'app/chat/components/RoomList.vue', { props: {
    rooms: [], showFilters: true, canCreate: false, canImpersonate: true, viewerAgentId: null,
    viewerAgents: [{ agent_id: 7, display_name: 'Alice', has_avatar: false }],
    includeExternal: false, includeArchived: false, hasMore: false, loadingMore: false,
  } })
  const viewer = page.locator('.viewer-select')
  await expect(viewer).toContainText('Me')
  await expect(viewer.getByRole('button', { name: 'Clear' })).toHaveCount(0)
  await viewer.getByRole('combobox').click()
  await page.getByRole('option').filter({ has: page.getByText('Alice', { exact: true }) }).click()
  await expect.poll(() => events(page, 'view-agent')).toEqual([[7]])
  await page.evaluate(() => window.testApp.setProps({ viewerAgentId: 7 }))
  await expect(viewer).toContainText('Alice')
  await expect(viewer.getByRole('button', { name: 'Clear' })).toHaveCount(0)
  await viewer.getByRole('combobox').press('Backspace')
  expect(await events(page, 'view-agent')).toEqual([[7]])
  await viewer.getByRole('combobox').click()
  await page.getByRole('option').filter({ has: page.getByText('Me', { exact: true }) }).click()
  await expect.poll(() => events(page, 'view-agent')).toEqual([[7], [null]])
  await page.evaluate(() => window.testApp.setProps({ viewerAgentId: null }))
  await expect(viewer).toContainText('Me')
})

test('unread room badges and archive filters expose actionable, independent controls', async ({ page }) => {
  await page.route('**/api/chat/agents/7/avatar', route => route.fulfill({ status: 404, body: '' }))
  await mount(page, 'app/chat/components/RoomList.vue', { props: {
    rooms: [{ id: 'room-a', agent_id: 7, label: 'Unread room', unread_count: 4, messenger_active: true, messenger_label: 'Web', agent_name: 'Alice', show_last_message: true }],
    selectedId: '', canCreate: true, canImpersonate: false, viewerAgentId: null, viewerAgents: [], includeExternal: false, includeArchived: false, hasMore: false, loadingMore: false,
  } })
  await expect(page.locator('.room-item--unread')).toHaveCount(1)
  await expect(page.locator('.room-item--unread .q-badge')).toHaveAttribute('aria-label', /4/)
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ showFilters: true }))
  await expect(page.getByRole('checkbox')).toHaveCount(2)
  await page.getByRole('checkbox').last().click()
  await expect.poll(() => events(page, 'toggle-archived')).toEqual([[true]])
  expect(await events(page, 'toggle-external')).toEqual([])
  await page.evaluate(() => window.testApp.setProps({ includeArchived: true, showFilters: false }))
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await page.evaluate(() => window.testApp.setProps({ showFilters: true }))
  await expect(page.getByRole('checkbox').last()).toBeChecked()
})
