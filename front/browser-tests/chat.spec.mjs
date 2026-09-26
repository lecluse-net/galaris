import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document as documentFixture } from './data.mjs'

const events = (page, name) => page.evaluate(name => window.testApp.events.filter(event => event.name === name).map(event => event.args), name)

test('room creation validates identity and name, and emits all preferences together', async ({ page }) => {
  await jsonRoute(page, '**/api/agents/selection?scope=dialogue', [{ id: 7, label: 'Alice', has_avatar: false }])
  await page.route('**/api/chat/agents/7/avatar', route => route.fulfill({ status: 404, body: '' }))
  await mount(page, 'app/chat/components/RoomCreateDialog.vue', { props: { modelValue: true, agents: [{ agent_id: 7, display_name: 'Alice', has_avatar: false }] } })
  const create = page.getByRole('button', { name: 'Chat', exact: true })
  await expect(create).toBeDisabled()
  await page.getByRole('combobox', { name: 'Agent', exact: true }).click()
  await page.getByRole('option', { name: 'Alice' }).click()
  const label = page.getByRole('textbox', { name: 'Conversation name', exact: true })
  await expect(label).toHaveValue('Alice')
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
  await expect(input).toHaveValue('')
  await expect(slider).toHaveCount(0)
  await input.fill('Ordinary message')
  await input.press('Enter')
  await expect.poll(() => events(page, 'send')).toHaveLength(2)
  expect((await events(page, 'send'))[1]).toEqual(['Ordinary message', undefined, undefined, false])
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
    await expect(input).toHaveValue('')
    await expect(post).toBeDisabled()

    await page.locator('input[type=file]').setInputFiles({ name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('Notes') })
    await expect(post).toBeEnabled()
    const upload = page.getByRole('button', { name: 'Add attachments', exact: true })
    const nextFile = page.waitForEvent('filechooser')
    if (width >= 1024) {
      const zone = await upload.boundingBox()
      const lastFile = await upload.locator('.attachment-item').last().boundingBox()
      await upload.click({ position: { x: zone.width / 2, y: lastFile.y + lastFile.height - zone.y + 10 } })
    } else {
      await upload.click()
    }
    await (await nextFile).setFiles({ name: 'extra.txt', mimeType: 'text/plain', buffer: Buffer.from('Extra') })
    await page.evaluate(() => window.testApp.setProps({ sending: true }))
    await expect(post).toBeDisabled()
    await input.press('Enter')
    await expect.poll(() => events(page, 'send')).toHaveLength(1)
    await page.evaluate(() => window.testApp.setProps({ sending: false }))
    await post.click()
    await expect.poll(() => page.evaluate(() => {
      const sent = window.testApp.events.filter(event => event.name === 'send').at(-1)
      return [sent.args[0], sent.args[1]?.map(file => file.name)]
    })).toEqual(['', ['notes.txt', 'extra.txt']])
    await expect(post).toBeDisabled()
  })
}

test('conversation process states and opening details follow the loaded data', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/rooms/room-a/processes?*', { items: [{ id: 'process-a', label: 'Image export', status: 'running', input: { format: 'png' }, output: null, error_message: null, created_at: '2026-09-01T12:00:00Z' }], total: 1 })
  await mount(page, 'app/chat/components/ConversationProcessesPanel.vue', { props: { roomId: 'room-a', fromMessageId: 'message-a', canRead: true } })
  await expect(page.locator('.q-item .q-spinner').first()).toBeVisible()
  await page.locator('.q-item').first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.locator('textarea.code-editor').first()).toHaveValue(/png/)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('conversation documents hide UUID labels and respect read and edit permissions', async ({ page }) => {
  await jsonRoute(page, '**/api/memory/items/doc-a?agent_id=7', { ...documentFixture, payload: { text: '<p>Working document</p>' } })
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
