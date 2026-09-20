import { test as base, expect } from '@playwright/test'

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
    // Ordinary component fixtures use Alice (7) as the managed agent. Scope tests override this catalogue.
    await page.route('**/api/agents/selection?scope=management', route => route.fulfill({ json: [{ id: 7, label: 'Alice Example', has_avatar: false }] }))
    await page.route('**/api/memory/documents/*/sharing', route => route.fulfill({ json: { lock_version: 1, can_manage: true, grants: [], options: [], level: 'private', can_write: false, owner: { kind: 'agent', id: 7, label: 'Alice', can_write: true }, owner_groups: [] } }))
    // Most documents use the standard icon. Icon scenarios override this explicit default.
    await page.route('**/api/memory/documents/icons/resolve', route => route.fulfill({ json: {} }))
    // Optional document captures are unavailable unless the scenario supplies a rendered image.
    await page.route('**/api/memory/documents/*/thumbnail*', route => route.fulfill({ status: 204 }))
    await use(page)
    if (!page.isClosed()) {
      failures.push(...await page.evaluate(() => window.testApp?.errors ?? []))
      await page.evaluate(() => window.testApp?.unmount?.())
    }
    expect(failures).toEqual([])
  },
})
export { expect }

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
