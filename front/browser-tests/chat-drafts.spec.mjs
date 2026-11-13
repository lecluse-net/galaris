import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const composer = 'app/chat/components/Composer.vue'
const props = { roomId: 'room-a', sending: false }
const local = page => page.evaluate(() => JSON.parse(localStorage.getItem('galaris:chat-draft:v1:1:room-a')))
const acknowledge = (page, accepted) => page.evaluate(accepted => window.testApp.events.filter(e => e.name === 'send').at(-1).args[4](accepted), accepted)

for (const [width, dark] of [[1440, false], [390, true]]) test(`draft text and attachment survive reload, room navigation and failed send at ${width}px; success keeps later typing`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  // Composer inherits these tokens from the actual Chat shell in normal use.
  const containerStyle = dark ? { '--chat-surface': '#1b1e23', '--chat-surface-soft': '#22262c', '--chat-text': '#e7ebf2', '--chat-text-secondary': '#c3ccda' } : {}
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  await mount(page, composer, { props, dark, containerStyle })
  const input = page.locator('textarea')
  await input.fill('Unsent synthetic text')
  await expect.poll(async () => (await local(page)).content.text).toBe('Unsent synthetic text')
  await page.locator('input[type=file]').setInputFiles({ name: 'draft.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic draft file') })
  await expect.poll(async () => (await local(page)).content.files[0]?.uploaded).toBe(true)
  // A full page reload destroys every component ref; both local and server recovery remain available.
  await mount(page, composer, { props, dark, containerStyle })
  await expect(input).toHaveValue('Unsent synthetic text')
  await expect(page.getByRole('button', { name: 'Remove draft.txt', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('restored-draft.png') })
  await page.evaluate(() => window.testApp.setProps({ roomId: 'room-b' }))
  await expect(input).toHaveValue('')
  await input.fill('Another conversation')
  await page.evaluate(() => window.testApp.setProps({ roomId: 'room-a' }))
  await expect(input).toHaveValue('Unsent synthetic text')
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(e => e.name === 'send').length)).toBe(1)
  await acknowledge(page, false)
  await expect(input).toHaveValue('Unsent synthetic text')
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(e => e.name === 'send').length)).toBe(2)
  await input.fill('Text typed during send')
  await acknowledge(page, true)
  await expect(input).toHaveValue('Text typed during send')
  await expect.poll(async () => (await local(page)).content.text).toBe('Text typed during send')
  await expect(page.getByRole('button', { name: 'Remove draft.txt', exact: true })).toHaveCount(0)
})

test('offline typing is recoverable immediately and retries synchronization after reconnection', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  let available = false
  let serverUser = 1
  let remote = { revision: 0, content: null }
  await page.route('**/api/chat/rooms/room-a/draft', route => {
    if (!available) return route.fulfill({ status: 503, json: { detail: 'Synthetic outage' } })
    if (serverUser === 2) return route.fulfill({ json: { revision: 0, content: null } })
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON()
      remote = { revision: body.expected_revision + 1, content: body.content }
    }
    return route.fulfill({ json: remote })
  })
  await mount(page, composer, { props })
  await page.locator('textarea').fill('Offline synthetic text')
  await expect.poll(async () => (await local(page)).content.text).toBe('Offline synthetic text')
  await mount(page, composer, { props })
  await expect(page.locator('textarea')).toHaveValue('Offline synthetic text')
  available = true
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect.poll(() => remote.content?.text).toBe('Offline synthetic text')
  await expect.poll(async () => (await local(page)).dirty).toBe(false)
  // A server-only restore works after removing the local snapshot, with no user mixing.
  await page.evaluate(() => localStorage.removeItem('galaris:chat-draft:v1:1:room-a'))
  await mount(page, composer, { props })
  await expect(page.locator('textarea')).toHaveValue('Offline synthetic text')
  serverUser = 2
  await page.evaluate(() => window.testApp.auth.$patch({ user: { id: 2, email: 'other@example.invalid' } }))
  await expect(page.locator('textarea')).toHaveValue('')
  // Server API isolation is separately verified with real authenticated users.
  await expect.poll(() => page.evaluate(() => localStorage.getItem('galaris:chat-draft:v1:2:room-a') !== null)).toBe(true)
  serverUser = 1
  await page.evaluate(() => window.testApp.auth.$patch({ user: { id: 1, email: 'first@example.invalid' } }))
  await expect(page.locator('textarea')).toHaveValue('Offline synthetic text')
})

test('late server reads cannot replace text typed during loading', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  let finish
  const gate = new Promise(resolve => { finish = resolve })
  await page.route('**/api/chat/rooms/room-a/draft', async route => {
    if (route.request().method() === 'PUT') return route.fulfill({ json: { revision: 1, content: route.request().postDataJSON().content } })
    await gate
    return route.fulfill({ json: { revision: 0, content: null } })
  })
  await mount(page, composer, { props })
  await page.locator('textarea').fill('New local typing')
  finish()
  await expect(page.locator('textarea')).toHaveValue('New local typing')
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect.poll(async () => (await local(page)).dirty).toBe(false)
})

test('lost save receipt is retried before synchronizing subsequent typing', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  let remote = { revision: 0, content: null }
  let mutation = null
  let lost = false
  await page.route('**/api/chat/rooms/room-a/draft', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: remote })
    const body = route.request().postDataJSON()
    if (body.mutation_key !== mutation) {
      if (body.expected_revision !== remote.revision) return route.fulfill({ status: 409, json: { detail: 'Stale revision' } })
      mutation = body.mutation_key
      remote = { revision: remote.revision + 1, content: body.content }
    }
    if (!lost) { lost = true; return route.abort('failed') }
    return route.fulfill({ json: remote })
  })
  await mount(page, composer, { props })
  await page.locator('textarea').fill('First saved text')
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect.poll(() => lost).toBe(true)
  await expect.poll(async () => Boolean((await local(page)).pending)).toBe(true)
  await page.locator('textarea').fill('More recent local text')
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect.poll(() => remote.content?.text).toBe('More recent local text')
  await expect.poll(async () => (await local(page)).dirty).toBe(false)
  await expect(page.locator('textarea')).toHaveValue('More recent local text')
})

test('server conflict preserves local text and requires confirmation before replacement', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  await mount(page, composer, { props })
  await page.locator('textarea').fill('Local text to preserve')
  let remote = { revision: 4, content: { client_message_id: 'server-key', text: 'Other editor text', files: [], resources: [], effort: 2 } }
  await page.route('**/api/chat/rooms/room-a/draft', route => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON()
      if (body.expected_revision !== remote.revision) return route.fulfill({ status: 409, json: { detail: 'Conflict' } })
      remote = { revision: remote.revision + 1, content: body.content }
    }
    return route.fulfill({ json: remote })
  })
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  const replace = page.getByRole('button', { name: 'Keep this draft', exact: true })
  await expect(replace).toBeVisible()
  await expect(page.locator('textarea')).toHaveValue('Local text to preserve')
  await replace.click()
  await expect(page.getByRole('dialog')).toBeVisible()
  expect(remote.content.text).toBe('Other editor text')
  await page.getByRole('dialog').getByRole('button', { name: 'Keep this draft', exact: true }).click()
  await expect.poll(() => remote.content.text).toBe('Local text to preserve')
})

test('a previous composer cannot overwrite the recovery snapshot after remount', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  let release
  let started = false
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/chat/rooms/room-a/draft', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { revision: 0, content: null } })
    started = true
    const body = route.request().postDataJSON()
    await gate
    return route.fulfill({ json: { revision: 1, content: body.content } })
  })
  await mount(page, composer, { props })
  await page.locator('textarea').fill('Before navigation')
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect.poll(() => started).toBe(true)
  await mount(page, composer, { props })
  await page.locator('textarea').fill('After remount')
  release()
  await expect.poll(async () => (await local(page)).content.text).toBe('After remount')
  await expect(page.locator('textarea')).toHaveValue('After remount')
})

test('a second attachment selected during an upload is saved before sending', async ({ page }) => {
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  let release
  let uploads = 0
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/chat/rooms/room-a/draft/files/*', async route => {
    uploads += 1
    const index = uploads
    if (index === 1) await gate
    return route.fulfill({ json: { key: route.request().url().split('/').at(-1), name: `file-${index}.txt`, mime: 'text/plain', size: 1, uploaded: true } })
  })
  await mount(page, composer, { props })
  await page.locator('input[type=file]').setInputFiles({ name: 'file-1.txt', mimeType: 'text/plain', buffer: Buffer.from('A') })
  await expect.poll(() => uploads).toBe(1)
  await page.locator('input[type=file]').setInputFiles({ name: 'file-2.txt', mimeType: 'text/plain', buffer: Buffer.from('B') })
  await expect(page.getByRole('button', { name: 'Remove file-2.txt', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Post', exact: true }).click()
  release()
  await expect.poll(() => uploads).toBe(2)
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(e => e.name === 'send').length)).toBe(1)
  expect((await local(page)).content.files.every(file => file.uploaded)).toBe(true)
  await acknowledge(page, true)
})
