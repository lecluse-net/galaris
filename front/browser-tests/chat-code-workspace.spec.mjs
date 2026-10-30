import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

async function setup(page, { directory = false, codeAccess = true, workspaceLabel = 'Synthetic repository' } = {}) {
  const room = { id: 'room-a', label: 'Synthetic code discussion', agent_id: 7, agent_name: 'Alice', agent_active: false, source: null, writable: true, members: [], muted: false, archived: false, unread_count: 0, conversation_type: 'text' }
  const workspace = { id: 'code-a', uri: 'galaris://code/code-a', label: workspaceLabel, mode: 'edit' }
  const message = { id: 'message-a', room_id: room.id, text: `Synthetic discussion remains available${directory ? ' console://synthetic-project/' : ''}`, files: [], sender: null, created_at: '2026-10-01T12:00:00Z', is_mine: true, status: 'sent' }
  const directoryRequests = []
  if (directory) {
    await jsonRoute(page, '**/api/chat/rooms/room-a/messages/message-a/previews', [{
      uri: 'console://synthetic-project/', kind: 'file', title: 'Synthetic project', subtitle: '', description: '',
      media_type: 'application/octet-stream', content: null, content_format: 'none', deleted: false,
      image_available: false, download_available: false, open_mode: 'inline', metadata: { is_collection: true },
    }])
    await page.route('**/api/chat/rooms/room-a/messages/message-a/previews/repository?*', route => {
      directoryRequests.push(new URL(route.request().url()).searchParams.get('uri'))
      return route.fulfill({ json: workspace })
    })
  }
  for (const [url, data] of [
    ['**/api/chat/status', { enabled: true, chat_enabled: true, max_attachment_bytes: 1000000 }],
    ['**/api/chat/rooms?*', { items: [room], total: 1 }], ['**/api/chat/rooms/room-a', room],
    ['**/api/chat/rooms/room-a/activity?*', { items: [], total: 0 }],
    ['**/api/chat/rooms/room-a/messages?*', { items: [message], total: 1 }],
    ['**/api/chat/rooms/room-a/read', {}], ['**/api/chat/inbox', { unread_count: 0 }],
    ['**/api/chat/rooms/room-a/commands', { commands: [] }],
    ['**/api/chat/rooms/room-a/speech/status*', { available_agent_ids: [] }],
    ['**/api/chat/emojis/frequent', { items: [] }], ['**/api/chat/agents/7/avatar', {}], ['**/api/agents?*', [agent]],
    ['**/api/chat/rooms/room-a/documents?*', { items: [{ id: 'doc-a', label: 'Synthetic document', uri: 'document://doc-a', revision: 1 }], total: 1 }],
    ['**/api/documents/doc-a?*', { item: { ...documentFixture, id: 'doc-a', title: 'Synthetic document', media_type: 'text/html', content_profile: 'document', payload: { text: '<p>Synthetic document body</p>' } }, agent_id: 7 }],
    ['**/api/documents/doc-a/attachments*', []], ['**/api/documents/keywords*', []],
    ['**/api/documents/folders*', []], ['**/api/documents/owner-options?*', { agents: [], users: [] }],
    ['**/api/code/rooms/room-a', [workspace]], ['**/api/code/sessions/*/heartbeat', { state: 'ready' }],
    ['**/api/chat/rooms/room-a/repositories', { paths: [], truncated: false }],
    ['**/api/code/sessions/*/navigate', { state: 'requested' }],
  ]) await jsonRoute(page, url, data)
  const opens = []
  const closes = []
  await page.route('**/api/code/workspaces/*/sessions', route => {
    const id = route.request().url().split('/workspaces/')[1].split('/')[0]
    opens.push(id)
    return route.fulfill({ json: { id: `session-${id}`, workspace: { ...workspace, id, label: id === 'code-b' ? 'Second repository' : workspace.label }, url: `http://localhost:8000/code-fixture/${id}`, expires_at: '2099-01-01T00:00:00Z' } })
  })
  await page.route('**/api/code/sessions/session-*', route => { closes.push(route.request().url()); return route.fulfill({ json: { state: 'closed' } }) })
  await page.route('**/code-fixture/*', route => {
    const id = route.request().url().split('/').at(-1)
    // This fixture tests iframe retention only. Native IDE behavior has a separate real-runtime suite.
    return route.fulfill({ contentType: 'text/html', body: `<textarea aria-label="Synthetic unsaved source"></textarea><script>parent.postMessage({type:'galaris.code.ready',session:'session-${id}'},location.origin)</script>` })
  })
  await mount(page, 'test-support/browser/CodeChatHarness.vue', { route: '/chat?room=room-a', privileges: ['CHAT_SEND', 'DOCUMENT_ACCESS', 'DOCUMENT_EDIT', ...(codeAccess ? ['CODE_ACCESS'] : [])] })
  await expect(page.locator('.conversation-pane')).toContainText(message.text)
  return { opens, closes, directoryRequests }
}

for (const width of [1280, 390]) {
test(`a restarted runtime preserves both drafts and confirms recovery replacement (${width})`, async ({ page }) => {
  await page.setViewportSize({ width, height: 844 })
  await page.clock.install()
  const state = await setup(page)
  let stopped = false
  let resumes = 0
  await page.route('**/api/code/sessions/session-code-a/heartbeat', route => route.fulfill(stopped
    ? { status: 410, json: { detail: 'Synthetic stopped runtime' } }
    : { json: { state: 'ready' } }))
  await page.route('**/api/code/sessions/session-code-a/resume', route => {
    resumes += 1
    stopped = false
    return route.fulfill({ json: { restart_required: true, url: 'http://localhost:8000/code-fixture/recovered' } })
  })
  await page.route('**/code-fixture/recovered', route => route.fulfill({ contentType: 'text/html',
    body: '<textarea aria-label="Synthetic recovered source"></textarea><script>parent.postMessage({type:"galaris.code.ready",session:"session-code-a"},location.origin)</script>',
  }))
  await show(page)
  const original = page.frameLocator('iframe.code-editor-frame:not(.code-recovery-frame)').getByRole('textbox')
  await original.fill('Synthetic original draft')
  stopped = true
  await page.clock.fastForward(30_000)
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  const fresh = page.frameLocator('iframe.code-recovery-frame').getByRole('textbox')
  await fresh.fill('Synthetic second draft')
  await expect(page.locator('iframe.code-editor-frame')).toHaveCount(2)
  await page.getByRole('button', { name: 'Show previous window' }).click()
  await expect(original).toHaveValue('Synthetic original draft')
  await page.getByRole('button', { name: 'Show recovered editor' }).click()
  await expect(fresh).toHaveValue('Synthetic second draft')
  stopped = true
  await page.clock.fastForward(30_000)
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  const confirmation = page.getByRole('dialog', { name: 'Reload the recovery editor', exact: true })
  await expect(confirmation).toContainText('Save or copy changes')
  await page.locator('.q-dialog__backdrop').last().click({ position: { x: 2, y: 2 } })
  await expect(confirmation).toHaveCount(0)
  await expect(page.locator('iframe.code-recovery-frame')).toBeVisible()
  await expect(fresh).toHaveValue('Synthetic second draft')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await page.getByRole('button', { name: 'Reload after saving' }).click()
  await expect(fresh).toHaveValue('')
  await expect(page.locator('iframe.code-editor-frame')).toHaveCount(2)
  await page.getByRole('button', { name: 'Show previous window' }).click()
  await expect(original).toHaveValue('Synthetic original draft')
  expect(resumes).toBe(2)
  expect(state.opens).toEqual(['code-a'])
  expect(state.closes).toEqual([])
})
}

for (const width of [1280, 390]) {
test(`clicking a Console directory opens the editor and reuses its unsaved contents on reopening (${width})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 844 })
  const state = await setup(page, { directory: true })
  const navigation = []
  await page.route('**/api/code/sessions/session-code-a/navigate', route => {
    navigation.push(route.request().postDataJSON())
    return route.fulfill({ json: { state: 'requested' } })
  })
  const card = page.locator('.resource-preview-card').filter({ hasText: 'Synthetic project' })
  await card.getByRole('button', { name: 'Open Synthetic project in the code editor' }).first().click()
  const source = page.frameLocator('iframe.code-editor-frame').getByRole('textbox', { name: 'Synthetic unsaved source' })
  await source.fill('Synthetic directory draft')
  await expect(page.getByRole('dialog', { name: 'Resource preview', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Hide editor', exact: true }).click()
  await card.getByRole('button', { name: 'Open Synthetic project in the code editor' }).first().focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('iframe.code-editor-frame')).toBeVisible()
  await expect(source).toHaveValue('Synthetic directory draft')
  expect(state.opens).toEqual(['code-a'])
  expect(state.directoryRequests).toEqual(['console://synthetic-project/', 'console://synthetic-project/'])
  expect(navigation).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('directory-editor.png'), animations: 'disabled' })
})
}

test('a late directory resolution cannot replace a newer repository request', async ({ page }) => {
  const state = await setup(page, { directory: true })
  let release
  const waiting = new Promise(resolve => { release = resolve })
  await page.route('**/api/chat/rooms/room-a/messages/message-a/previews/repository?*', async route => {
    await waiting
    await route.fulfill({ json: { id: 'code-a', label: 'Synthetic project', mode: 'edit' } })
  })
  const resolving = page.waitForRequest('**/api/chat/rooms/room-a/messages/message-a/previews/repository?*')
  await page.getByRole('button', { name: 'Open Synthetic project in the code editor' }).first().click()
  await resolving
  await show(page, 'code-b', '2')
  await expect(page.locator('.code-workspace-pane')).toContainText('Second repository')
  const response = page.waitForResponse('**/api/chat/rooms/room-a/messages/message-a/previews/repository?*')
  release()
  await (await response).finished()
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)))
  await expect(page.locator('iframe.code-editor-frame')).toHaveCount(1)
  await expect(page.locator('.code-workspace-pane')).toContainText('Second repository')
  expect(state.opens).toEqual(['code-b'])
})

test('a directory without editor access stays a readable reference without opening an empty preview', async ({ page }) => {
  const state = await setup(page, { directory: true, codeAccess: false })
  const card = page.locator('.resource-preview-card').filter({ hasText: 'Synthetic project' })
  await expect(card).toBeVisible()
  await expect(card.getByRole('button')).toHaveCount(0)
  await card.click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(state.directoryRequests).toEqual([])
  expect(state.opens).toEqual([])
})

for (const [status, detail, message] of [
  [503, 'code_runtime_not_configured', 'The editor is not configured for this external Console'],
  [422, 'code_directory_not_repository', 'This folder must belong to a Git repository'],
  [403, 'Repository unavailable', 'Code editor unavailable'],
]) {
test(`a directory open failure (${status}) keeps the conversation usable without an empty preview`, async ({ page }) => {
  const state = await setup(page, { directory: true })
  await page.route(status === 503 ? '**/api/code/workspaces/code-a/sessions'
    : '**/api/chat/rooms/room-a/messages/message-a/previews/repository?*', route =>
    route.fulfill({ status, json: { detail } }))
  await page.getByRole('button', { name: 'Open Synthetic project in the code editor' }).first().click()
  await expect(page.getByRole('alert')).toContainText(message)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('iframe.code-editor-frame')).toHaveCount(0)
  await expect(page.getByPlaceholder('Write a message…')).toBeVisible()
  expect(state.opens).toEqual([])
})
}

async function show(page, id = 'code-a', sequence = '1', room = 'room-a') {
  await page.evaluate(data => window.testApp.emitSocket('chat.repository_show', { data }), { room_id: room, workspace_id: id, sequence, view: 'changes' })
}

for (const width of [1280, 390]) {
test(`discovery opens a home-relative path without needing a message from the agent (${width})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 844 })
  // A previous checkout at this path must not hide its newly discovered identity.
  const state = await setup(page, { workspaceLabel: 'work/project #1' })
  const registered = []
  await page.route('**/api/chat/rooms/room-a/repositories*', route => {
    if (route.request().method() === 'POST') {
      registered.push(new URL(route.request().url()).searchParams.get('uri'))
      return route.fulfill({ json: { id: 'code-new', label: 'work/project #1', mode: 'edit' } })
    }
    return route.fulfill({ json: { paths: ['work/project #1', 'archive/project #1'], truncated: false } })
  })
  if (width < 1024) await page.getByRole('button', { name: 'Details', exact: true }).click()
  await page.getByText('Source code', { exact: true }).click()
  await expect(page.getByText('archive/project #1', { exact: true })).toBeVisible()
  const repository = page.getByRole('button', { name: 'work/project #1', exact: true, includeHidden: true })
  await expect(repository).not.toHaveAttribute('aria-current', 'true')
  await repository.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('repository-list.png'), animations: 'disabled' })
  await repository.focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('iframe.code-editor-frame')).toBeVisible()
  expect(registered).toEqual(['console://work/project%20%231/'])
  expect(state.opens).toEqual(['code-new'])
  await expect(repository).toHaveAttribute('aria-current', 'true')
  await page.screenshot({ path: testInfo.outputPath('discovered-repository.png'), animations: 'disabled' })
})
}

test('failed discovery preserves linked repositories and refresh recovers a partial search', async ({ page }) => {
  await setup(page)
  let calls = 0
  await page.route('**/api/chat/rooms/room-a/repositories', route => {
    calls += 1
    return route.fulfill(calls === 1 ? { status: 503, json: { detail: 'code_discovery_unavailable' } }
      : { json: { paths: ['work/project'], truncated: true } })
  })
  await page.getByText('Source code', { exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Unable to discover repositories')
  await expect(page.getByText('Synthetic repository', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Refresh repositories', exact: true }).click()
  await expect(page.getByText('work/project', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('Synthetic repository', { exact: true })).toBeVisible()
})

test('a collapsed discovery ignores its late response when reopened', async ({ page }) => {
  await setup(page)
  let release
  const pending = new Promise(resolve => { release = resolve })
  let calls = 0
  await page.route('**/api/chat/rooms/room-a/repositories', async route => {
    calls += 1
    if (calls === 1) {
      await pending
      await route.fulfill({ json: { paths: ['stale/project'], truncated: false } })
    } else await route.fulfill({ json: { paths: ['fresh/project'], truncated: false } })
  })
  const started = page.waitForRequest('**/api/chat/rooms/room-a/repositories')
  await page.getByText('Source code', { exact: true }).click()
  await started
  await page.getByText('Source code', { exact: true }).click()
  await page.getByText('Source code', { exact: true }).click()
  await expect(page.getByText('fresh/project', { exact: true })).toBeVisible()
  release()
  await expect(page.getByText('stale/project', { exact: true })).toHaveCount(0)
})

test('an unprepared external Console explains the failure and can be opened after configuration', async ({ page }) => {
  const state = await setup(page)
  const failures = []
  page.on('pageerror', error => failures.push(error.message))
  await page.route('**/api/code/workspaces/code-a/sessions', route => route.fulfill({
    status: 503, json: { detail: 'code_runtime_not_configured' },
  }))
  await show(page)
  await expect(page.getByRole('alert')).toContainText('The editor is not configured for this external Console')
  await expect(page.locator('iframe.code-editor-frame')).toHaveCount(0)
  await expect(page.locator('.conversation-pane')).toContainText('Synthetic discussion remains available')
  await page.unroute('**/api/code/workspaces/code-a/sessions')
  await show(page, 'code-a', '2')
  await expect(page.locator('iframe.code-editor-frame')).toBeVisible()
  expect(state.opens).toEqual(['code-a'])
  expect(failures).toEqual([])
})

test('unsaved iframe contents survive code, document and code transitions', async ({ page }) => {
  const state = await setup(page)
  await page.getByText('Source code', { exact: true }).click()
  const repository = page.getByRole('button', { name: 'Synthetic repository', exact: true })
  await show(page)
  const iframe = page.locator('iframe.code-editor-frame')
  await expect(iframe).toBeVisible()
  await expect(repository).toHaveAttribute('aria-current', 'true')
  const source = page.frameLocator('iframe.code-editor-frame').getByRole('textbox', { name: 'Synthetic unsaved source' })
  await source.fill('Unsaved human source')
  await page.evaluate(() => window.testApp.emitSocket('chat.document_show', { data: { room_id: 'room-a', document_id: 'doc-a' } }))
  await expect(page.locator('.chat-document-pane')).toContainText('Synthetic document body')
  await expect(iframe).toBeHidden()
  await expect(repository).not.toHaveAttribute('aria-current', 'true')
  await show(page, 'code-a', '2')
  await expect(iframe).toBeVisible()
  await expect(source).toHaveValue('Unsaved human source')
  await expect(repository).toHaveAttribute('aria-current', 'true')
  await page.getByRole('button', { name: 'Hide editor', exact: true }).click()
  await expect(repository).not.toHaveAttribute('aria-current', 'true')
  expect(state.opens).toEqual(['code-a'])
  expect(state.closes).toEqual([])
})

test('application theme changes preserve the editor without requiring a runtime theme API', async ({ page }) => {
  const state = await setup(page)
  const themes = []
  await page.route('**/api/code/sessions/session-code-a/theme', route => {
    themes.push(route.request().postDataJSON().theme)
    return route.fulfill({ status: 503, json: { detail: 'Synthetic legacy runtime has no theme API' } })
  })
  const navigation = []
  await page.route('**/api/code/sessions/session-code-a/navigate', route => {
    navigation.push(route.request().postDataJSON())
    return route.fulfill({ json: { state: 'requested' } })
  })
  await page.emulateMedia({ colorScheme: 'light' })
  await show(page)
  const source = page.frameLocator('iframe.code-editor-frame').getByRole('textbox', { name: 'Synthetic unsaved source' })
  await source.fill('Synthetic retained theme draft')
  await page.evaluate(() => window.testApp.dark(true))
  await expect(page.locator('body')).toHaveClass(/body--dark/)
  await page.evaluate(() => window.testApp.dark(false))
  await expect(page.locator('body')).toHaveClass(/body--light/)
  await expect(source).toHaveValue('Synthetic retained theme draft')
  await page.evaluate(() => window.testApp.emitSocket('chat.repository_show', {
    data: { room_id: 'room-a', workspace_id: 'code-a', sequence: '2', file: 'synthetic.ts', view: 'files' },
  }))
  await expect.poll(() => navigation.at(-1)).toEqual({ file: 'synthetic.ts', view: 'files' })
  await expect(source).toHaveValue('Synthetic retained theme draft')
  expect(state.opens).toEqual(['code-a'])
  expect(themes).toEqual([])
})

test('older sequence and another room cannot replace the current repository', async ({ page }) => {
  const state = await setup(page)
  await show(page, 'code-b', '20')
  await expect(page.locator('.code-workspace-pane')).toContainText('Second repository')
  await show(page, 'code-a', '19')
  await show(page, 'code-a', '21', 'other-room')
  await expect(page.locator('.code-workspace-pane')).toContainText('Second repository')
  expect(state.opens).toEqual(['code-b'])
})

test('hiding and reopening a repository preserves the editor without navigating or closing its session', async ({ page }) => {
  const state = await setup(page)
  // Sample the host's document-wide layout scans over the same 12 frames in
  // each state. A retained, hidden editor must not keep polling the DOM.
  const layoutScans = () => page.evaluate(async () => {
    const query = document.querySelectorAll
    let scans = 0
    document.querySelectorAll = function (selector) {
      if (selector === '.q-dialog') scans += 1
      return query.call(this, selector)
    }
    try {
      for (let frame = 0; frame < 12; frame += 1) {
        await new Promise(resolve => requestAnimationFrame(resolve))
      }
      return scans
    } finally { document.querySelectorAll = query }
  })
  expect(await layoutScans(), 'no layout polling before opening an editor').toBe(0)
  await show(page)
  const iframe = page.locator('iframe.code-editor-frame')
  await expect(iframe).toBeVisible()
  const source = page.frameLocator('iframe.code-editor-frame').getByRole('textbox', { name: 'Synthetic unsaved source' })
  await source.fill('Synthetic retained repository draft')
  const navigation = []
  await page.route('**/api/code/sessions/session-code-a/navigate', route => {
    navigation.push(route.request().postDataJSON())
    return route.fulfill({ json: { state: 'requested' } })
  })
  await page.getByRole('button', { name: 'Hide editor', exact: true }).click()
  await expect(iframe).toBeHidden()
  expect(await layoutScans(), 'no layout polling while the editor is hidden').toBe(0)
  await page.getByText('Source code', { exact: true }).click()
  await page.locator('#chat-sidebar-content').getByText('Synthetic repository', { exact: true }).click()
  await expect(iframe).toBeVisible()
  await expect(source).toHaveValue('Synthetic retained repository draft')
  // Reopening must also resume alignment when the viewport changes, without
  // requiring a particular polling or observer implementation while visible.
  await page.setViewportSize({ width: 1180, height: 850 })
  await expect.poll(async () => {
    const frame = await iframe.boundingBox()
    const anchor = await page.locator('.code-workspace-anchor').boundingBox()
    if (!frame || !anchor) return Infinity
    return Math.max(...['x', 'y', 'width', 'height'].map(key => Math.abs(frame[key] - anchor[key])))
  }).toBeLessThan(1)
  expect(state.opens).toEqual(['code-a'])
  expect(state.closes).toEqual([])
  expect(navigation).toEqual([])
})

test('mobile document transitions retain the unsaved source and message draft', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await setup(page)
  await page.getByPlaceholder('Write a message…').fill('Synthetic message draft')
  await show(page)
  const iframe = page.locator('iframe.code-editor-frame')
  await expect(iframe).toBeVisible()
  const source = page.frameLocator('iframe.code-editor-frame').getByRole('textbox', { name: 'Synthetic unsaved source' })
  await source.fill('Synthetic mobile draft')
  await page.evaluate(() => window.testApp.emitSocket('chat.document_show', { data: { room_id: 'room-a', document_id: 'doc-a' } }))
  await expect(page.getByRole('dialog').getByRole('textbox', { name: 'Content', exact: true })).toContainText('Synthetic document body')
  await expect(iframe).toBeHidden()
  await show(page, 'code-a', '2')
  await expect(iframe).toBeVisible()
  await expect(source).toHaveValue('Synthetic mobile draft')
  await page.getByRole('button', { name: 'Hide editor', exact: true }).click()
  await expect(page.getByPlaceholder('Write a message…')).toHaveValue('Synthetic message draft')
  expect(state.opens).toEqual(['code-a'])
})

test('a late repository open cannot take focus from a newer request', async ({ page }) => {
  await setup(page)
  let release
  const waiting = new Promise(resolve => { release = resolve })
  await page.route('**/api/code/workspaces/code-a/sessions', async route => {
    await waiting
    await route.fulfill({ json: { id: 'session-code-a', workspace: { id: 'code-a', label: 'Late repository', mode: 'edit', branch: 'main' },
      url: 'http://localhost:8000/code-fixture/code-a', expires_at: '2099-01-01T00:00:00Z' } })
  })
  const first = page.waitForRequest('**/api/code/workspaces/code-a/sessions')
  await show(page)
  await first
  await show(page, 'code-b', '2')
  await expect(page.locator('.code-workspace-pane')).toContainText('Second repository')
  release()
  await expect(page.locator('iframe.code-editor-frame')).toHaveCount(2)
  await expect(page.locator('.code-workspace-pane')).toContainText('Second repository')
})

for (const status of [503, 410, 403]) {
test(`a lost heartbeat (${status}) retains the loaded buffer and retry respects session recovery and access`, async ({ page }) => {
  await page.clock.install()
  const state = await setup(page)
  let unavailable = true
  await page.route('**/api/code/sessions/session-code-a/heartbeat', route => route.fulfill(unavailable
    ? { status, json: { detail: 'Synthetic session interruption' } }
    : { json: { state: 'ready' } }))
  const resumes = []
  await page.route('**/api/code/sessions/session-code-a/resume', route => {
    resumes.push(route.request().method())
    unavailable = false
    return route.fulfill({ json: { state: 'ready' } })
  })
  await show(page)
  const source = page.frameLocator('iframe.code-editor-frame').getByRole('textbox', { name: 'Synthetic unsaved source' })
  await source.fill('Synthetic disconnected draft')
  await page.clock.fastForward(30_000)
  await expect(page.locator('.code-workspace-pane [role="alert"]')).toBeVisible()
  await expect(source).toHaveValue('Synthetic disconnected draft')
  if (status === 503) unavailable = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.locator('.code-workspace-pane [role="alert"]')).toHaveCount(status === 403 ? 1 : 0)
  await expect(source).toHaveValue('Synthetic disconnected draft')
  expect(state.opens).toEqual(['code-a'])
  expect(resumes).toEqual(status === 410 ? ['POST'] : [])
})
}
