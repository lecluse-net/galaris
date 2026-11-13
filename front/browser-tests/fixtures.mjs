import { test as base, expect } from '@playwright/test'
import { document as documentFixture } from './data.mjs'

export const test = base.extend({
  page: async ({ page }, use) => {
    const failures = []
    page.on('pageerror', error => failures.push(error.message))
    // An omitted fixture is an error, never an implicit successful empty response.
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      failures.push(`Unexpected API request: ${route.request().method()} ${route.request().url()}`)
      await route.fulfill({ status: 500, json: { detail: 'Missing component test fixture' } })
    })
    // Documents have no sharing in ordinary editor fixtures. Dedicated sharing tests override this route.
    // Help starts unread; persistence/error scenarios override this read-only fixture.
    await page.route('**/api/auth/me/help-dismissals', route => route.fulfill({ json: [] }))
    // Private chat drafts start empty. Dedicated recovery scenarios override failures/concurrency.
    const drafts = new Map()
    await page.route('**/api/chat/rooms/*/draft', route => {
      const room = new URL(route.request().url()).pathname
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON()
        drafts.set(room, { revision: body.expected_revision + 1, content: body.content })
      }
      return route.fulfill({ json: drafts.get(room) ?? { revision: 0, content: null } })
    })
    await page.route('**/api/chat/rooms/*/draft/files/*', async route => {
      if (route.request().method() === 'DELETE') return route.fulfill({ status: 204 })
      const key = new URL(route.request().url()).pathname.split('/').at(-1)
      const form = await (await fetch('data:application/octet-stream;base64,' + route.request().postDataBuffer().toString('base64'))).arrayBuffer()
      const request = new Request('http://fixture.invalid', { method: 'POST', headers: { 'content-type': route.request().headers()['content-type'] }, body: form })
      let file = (await request.formData()).get('file')
      // WebKit's Playwright interception omits binary multipart parts. Recover
      // the selected fixture bytes from IndexedDB; real multipart persistence is
      // exercised against the HTTP backend in test_attachment_http.py.
      if (page.context().browser().browserType().name() === 'webkit' && file.size === 0) {
        const room = new URL(route.request().url()).pathname.split('/')[4]
        const stored = await page.evaluate(async ({ room, key }) => {
          const { draftBlob, draftKey } = await import('/app/chat/drafts.ts')
          const file = await draftBlob(draftKey(window.testApp.auth.user.id, room), key)
          return file && { name: file.name, type: file.type, bytes: [...new Uint8Array(await file.arrayBuffer())] }
        }, { room, key })
        if (stored) file = new File([new Uint8Array(stored.bytes)], stored.name, { type: stored.type })
      }
      return route.fulfill({ json: { key, name: file.name, mime: file.type, size: file.size, uploaded: true } })
    })
    // Personal Goal classifications start empty; classification journeys override this.
    await page.route('**/api/goals/categories', route => route.fulfill({ json: [] }))
    // Ordinary component fixtures use Alice (7) as the managed agent. Scope tests override this catalogue.
    await page.route('**/api/agents/selection?scope=management', route => route.fulfill({ json: [{ id: 7, label: 'Alice Example', has_avatar: false }] }))
    await page.route('**/api/teams/human-selection', route => route.fulfill({ json: [{ id: 1, teams: [] }] }))
    await page.route('**/api/documents/*/sharing', route => route.fulfill({ json: { lock_version: 1, can_manage: true, grants: [], options: [], level: 'private', can_write: false, owner: { kind: 'agent', id: 7, label: 'Alice', can_write: true }, owner_groups: [] } }))
    await page.route('**/api/documents/*/dataset-attachments*', route => route.fulfill({ json: { items: [], lock_version: 1 } }))
    await page.route('**/api/documents/*/process-attachments*', route => route.fulfill({ json: { items: [], lock_version: 1 } }))
    await page.route('**/api/documents/*/internal-attachments*', route => route.fulfill({ json: { items: [], lock_version: 1 } }))
    await page.route('**/api/datasets?*', route => route.fulfill({ json: { items: [], total: 0 } }))
    // Most documents use the standard icon. Icon scenarios override this explicit default.
    await page.route('**/api/documents/icons/resolve', route => route.fulfill({ json: {} }))
    // Foreground Dream actions require explicit eligible-source fixtures.
    await page.route('**/api/dream/memory/*/actions?*', route => route.fulfill({ json: { actions: [] } }))
    // Graph persistence is empty unless a dedicated scenario supplies saved state.
    await page.route('**/api/memory/graph/state/read', route => route.fulfill({ json: {
      format_version: 1, revision: 0, preferences: { hidden_entity_kinds: [], expanded_branches: [], camera: null }, positions: {},
    } }))
    await page.route('**/api/memory/graph/state', route => {
      const body = route.request().postDataJSON()
      return route.fulfill({ json: { format_version: 1, revision: body.expected_revision + 1,
        preferences: { hidden_entity_kinds: [], expanded_branches: [], camera: null, ...body.preferences }, positions: body.positions } })
    })
    // Optional document captures are unavailable unless the scenario supplies a rendered image.
    await page.route('**/api/documents/*/thumbnail*', route => route.fulfill({ status: 204 }))
    await page.route('**/api/documents/import-formats', route => route.fulfill({ json: {
      extensions: ['.txt', '.md', '.json', '.html', '.htm', '.pdf', '.docx', '.odt', '.xls', '.xlsx', '.png'],
      media_types: ['text/plain', 'text/markdown', 'application/json', 'text/html', 'application/pdf', 'image/png'],
    } }))
    await use(page)
    if (!page.isClosed()) {
      failures.push(...await page.evaluate(() => window.testApp?.errors ?? []))
      await page.evaluate(() => window.testApp?.unmount?.())
    }
    expect(failures).toEqual([])
  },
})
export { expect }

// Select content without opening a link or invoking the browser's native menu.
export async function selectDocumentContext(page, target) {
  if (!await target.evaluate(element => Boolean(element.closest('.selectedCell')))) await target.click()
  await target.evaluate(element => {
    const editor = element.closest('[data-editor-surface]')
    if (element.closest('.selectedCell')) return
    const object = element.closest('.galaris-image-object, blockquote.galaris-link-card, .embedded-code-widget, [data-math]')
    if (object) {
      editor.editor.chain().setNodeSelection(editor.editor.view.posAtDOM(object, 0)).focus().run()
      return
    }
    const range = document.createRange()
    range.selectNodeContents(element)
    const selection = window.getSelection()
    selection.removeAllRanges()
    selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
    editor.editor.chain().setTextSelection({
      from: editor.editor.view.posAtDOM(range.startContainer, range.startOffset),
      to: editor.editor.view.posAtDOM(range.endContainer, range.endOffset),
    }).focus().run()
  })
  return page.getByRole('toolbar', { name: 'Contextual actions', exact: true })
}

// Inspect portable document HTML through the editor serializer, independently of UI controls.
export async function editorHtml(page) {
  return page.locator('[data-editor-surface]').evaluate(async element => {
    const { sanitizeRichHtml } = await import('/core/util/richText.ts')
    const { restoreInteractiveHtml } = await import('/core/util/interactiveHtml.ts')
    return restoreInteractiveHtml(sanitizeRichHtml(element.editor.getHTML(), 'document'))
  })
}

export async function mount(page, component, options = {}) {
  await page.route('**/api/authorize/my-privileges', route => route.fulfill({ json: options.privileges ?? [] }))
  await page.goto('/test-support/browser/index.html')
  await page.waitForFunction(() => window.testApp?.mount)
  await page.evaluate(args => {
    window.componentMount = { done: false, error: null }
    void window.testApp.mount(args).then(
      () => { window.componentMount.done = true },
      error => { window.componentMount.error = String(error.stack ?? error) },
    )
  }, { component, ...options })
  await page.waitForFunction(() => window.componentMount.done || window.componentMount.error)
  expect(await page.evaluate(() => window.componentMount.error)).toBeNull()
}

export async function setPrivileges(page, privileges) {
  await page.route('**/api/authorize/my-privileges', route => route.fulfill({ json: privileges }))
  await page.evaluate(() => window.testApp.privileges.refreshPrivileges())
}

export async function jsonRoute(page, url, json) {
  await page.route(url, route => route.fulfill({ json }))
}

// Read-only fixtures for Data links opened in the shared Document editor.
// Unexpected writes still reach the fixture guard and fail the scenario.
export async function dataDocumentRoutes(page, source, agentId = 7) {
  const item = { ...documentFixture, ...source, document_type: 'data', media_type: 'application/json',
    content_profile: 'document', content_profile_version: null,
    payload: { text: source.content }, access: { can_read: true, can_write: source.can_write === true } }
  await page.route(new RegExp(`/api/documents/${source.id}(?:\\?.*)?$`), route => route.request().method() === 'GET'
    ? route.fulfill({ json: { item, agent_id: agentId } }) : route.fallback())
  await jsonRoute(page, `**/api/documents/${source.id}/attachments*`, [])
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [] })
  return item
}
