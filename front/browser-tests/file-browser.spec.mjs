import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document } from './data.mjs'

const component = 'app/file_share/pages/index.vue'
const schemes = [
  { scheme: 'console', label: 'Console', capabilities: ['list', 'info', 'read'], native: true },
  { scheme: 'galaris', label: 'Galaris', capabilities: ['list', 'info', 'read'], native: true },
  { scheme: 'messenger', label: 'Messenger', capabilities: ['list', 'info', 'read'], native: true, root_listable: false },
  { scheme: 'https', label: 'HTTPS', capabilities: ['info', 'read'], native: true },
  { scheme: 'mail', label: 'Mail', capabilities: ['list', 'info', 'read'], native: false },
]
const entry = (uri, name, collection = false) => ({ uri, name, is_collection: collection,
  media_type: collection ? 'inode/directory' : 'text/plain', size: collection ? null : 24, capabilities: ['info', 'read'] })
const pageOf = (uri, entries, next_cursor = null) => ({ uri, entries, next_cursor, truncated: !!next_cursor })

async function setup(page) {
  await jsonRoute(page, '**/api/agents/selection?*', [
    { id: 7, label: 'Alice Example', has_avatar: false }, { id: 8, label: 'Bob Example', has_avatar: false },
  ])
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', schemes)
  await page.route('**/api/file-share/browser/thumbnail?*', route => route.fulfill({ status: 404 }))
}
async function selectAgent(page, name) {
  if (!await page.getByRole('combobox').count()) {
    await page.getByRole('button', { name: `Browse files for ${name}`, exact: true }).click()
    await expect(page.getByRole('combobox')).toBeVisible()
    return
  }
  await page.getByRole('combobox').click()
  await page.getByRole('option', { name, exact: true }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
}

test('opening a cached internal file rereads its registered name before previewing it', async ({ page }) => {
  await setup(page)
  const uri = 'file://00000000-0000-4000-8000-000000000004'
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'file', label: 'Files', capabilities: ['list'], native: true }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', pageOf('file://', [entry(uri, 'Old name.txt')]))
  await jsonRoute(page, '**/api/file-share/browser/info?*', entry(uri, 'Current registered name.txt'))
  await page.route('**/api/file-share/browser/content?*', route => route.fulfill({ contentType: 'text/plain', body: 'Synthetic file content' }))
  await mount(page, component, { route: '/files?agent_id=7', privileges: ['MEMORY_ACCESS'] })
  await page.getByText('file://', { exact: true }).click()
  await page.getByRole('button', { name: 'Open Old name.txt', exact: true }).click()
  await expect(page.getByRole('article', { name: 'Current registered name.txt', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Open Current registered name.txt', exact: true })).toBeVisible()
})

test('an existing file citation opens through authorized file sharing and retries denied access', async ({ page }) => {
  await setup(page)
  const uri = 'file://00000000-0000-4000-8000-000000000004'
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'file', label: 'Existing files', capabilities: ['list', 'info', 'read'], native: true }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', pageOf('file://', []))
  let denied = true, reads = 0
  await page.route('**/api/file-share/browser/info?*', route => {
    const params = new URL(route.request().url()).searchParams
    expect(params.get('agent_id')).toBe('7'); expect(params.get('uri')).toBe(uri)
    return route.fulfill(denied ? { status: 403, json: { detail: 'Synthetic unavailable file' } } : { json: entry(uri, 'Existing notes.txt') })
  })
  await page.route('**/api/file-share/browser/content?*', route => {
    reads++
    expect(new URL(route.request().url()).searchParams.get('uri')).toBe(uri)
    return route.fulfill({ contentType: 'text/plain', body: 'Existing source content' })
  })
  await mount(page, component, { route: `/files?agent_id=7&uri=${encodeURIComponent(uri)}`, privileges: ['MEMORY_ACCESS'] })
  await expect(page.getByRole('alert')).toBeVisible()
  expect(reads).toBe(0)
  denied = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Existing source content', { exact: true })).toBeVisible()
  expect(reads).toBe(1)
})

test('shared videos play from range URLs, release access on closing and reopen without a full download', async ({ page }) => {
  await setup(page)
  await mount(page, component, { privileges: ['MEMORY_ACCESS'] })
  const bytes = Buffer.from(await page.evaluate(async () => {
    const canvas = document.createElement('canvas')
    canvas.width = 64; canvas.height = 64
    const stream = canvas.captureStream(10)
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' })
    const chunks = []
    recorder.ondataavailable = event => chunks.push(event.data)
    const recording = new Promise(resolve => { recorder.onstop = () => resolve(new Blob(chunks)) })
    let frame = 0
    const timer = setInterval(() => {
      const context = canvas.getContext('2d')
      context.fillStyle = ++frame % 2 ? '#000000' : '#ffffff'
      context.fillRect(0, 0, 64, 64)
    }, 50)
    recorder.start()
    setTimeout(() => { clearInterval(timer); recorder.stop() }, 1000)
    const blob = await recording
    stream.getTracks().forEach(track => track.stop())
    return [...new Uint8Array(await blob.arrayBuffer())]
  }))
  const uri = 'console://Synthetic.webm'
  await jsonRoute(page, '**/api/file-share/browser/entries?*', pageOf('console://', [
    { ...entry(uri, 'Synthetic.webm'), media_type: 'video/webm', size: 3 * 1024 ** 3 },
  ]))
  let issued = 0, released = 0, downloads = 0, mediaReads = 0
  await page.route('**/api/file-share/browser/content?*', route => { downloads++; return route.abort() })
  await page.route('**/api/file-share/browser/media?*', route => {
    issued++
    return route.fulfill({ json: { url: `/api/file-share/browser/media/synthetic-${issued}` } })
  })
  await page.route('**/api/file-share/browser/media/synthetic-*', route => {
    if (route.request().method() === 'DELETE') { released++; return route.fulfill({ status: 204 }) }
    mediaReads++
    const selected = route.request().headers().range?.match(/^bytes=(\d+)-(\d*)$/)
    expect(selected).toBeTruthy()
    const start = Number(selected[1]), end = selected[2] ? Number(selected[2]) : bytes.length - 1
    return route.fulfill({ status: 206, body: bytes.subarray(start, end + 1), headers: {
      'content-type': 'video/webm', 'accept-ranges': 'bytes',
      'content-range': `bytes ${start}-${end}/${bytes.length}`,
    } })
  })
  await selectAgent(page, 'Alice Example')
  await page.getByText('Console', { exact: true }).click()
  for (let attempt = 1; attempt <= 2; attempt++) {
    await page.getByRole('button', { name: 'Open Synthetic.webm', exact: true }).click()
    const video = page.getByRole('dialog').locator('video')
    await expect(video).toBeVisible()
    await expect.poll(() => video.evaluate(element => element.readyState)).toBeGreaterThanOrEqual(1)
    await video.evaluate(element => { element.muted = true; return element.play() })
    await expect.poll(() => video.evaluate(element => element.currentTime)).toBeGreaterThan(0)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect.poll(() => released).toBe(attempt)
  }
  expect(issued).toBe(2)
  expect(mediaReads).toBeGreaterThanOrEqual(2)
  expect(downloads).toBe(0)
})

for (const width of [1440, 390]) test(`tree folders collapse and reopen on repeated clicks at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  await setup(page)
  let reads = 0
  await page.route('**/api/file-share/browser/entries?*', route => {
    const uri = new URL(route.request().url()).searchParams.get('uri')
    if (uri === 'console://') return route.fulfill({ json: pageOf(uri, [entry('console://reports/', 'Reports', true)]) })
    reads++
    return route.fulfill({ json: pageOf(uri, [
      entry('console://reports/archive/', 'Archive', true), entry('console://reports/notes.txt', 'Notes.txt'),
    ]) })
  })
  await mount(page, component, { route: '/files?agent_id=7', privileges: ['MEMORY_ACCESS'] })
  if (width === 390) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await page.getByText('Console', { exact: true }).click()
  const tree = page.locator('.file-tree')
  const reports = tree.getByText('Reports', { exact: true })
  await reports.click()
  if (width === 390) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await expect(tree.getByText('Archive', { exact: true })).toBeVisible()
  await reports.click()
  await expect(tree.getByText('Archive', { exact: true })).toBeHidden()
  await expect(page.locator('.file-main').getByRole('button', { name: 'Open Notes.txt', exact: true })).toBeVisible()
  await reports.click()
  await expect(tree.getByText('Archive', { exact: true })).toBeVisible()
  const reportsItem = tree.getByRole('treeitem', { name: 'Reports', exact: true })
  await reportsItem.press('Enter')
  await expect(tree.getByText('Archive', { exact: true })).toBeHidden()
  await reportsItem.press('Enter')
  await expect(tree.getByText('Archive', { exact: true })).toBeVisible()
  expect(reads).toBe(1)
})

for (const width of [1440, 390]) test(`browse folders, scroll, retry and preview with the keyboard at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  await setup(page)
  let failContinuation = true
  const calls = []
  await page.route('**/api/file-share/browser/entries?*', route => {
    const params = new URL(route.request().url()).searchParams
    const uri = params.get('uri'), cursor = params.get('cursor')
    calls.push({ uri, cursor })
    if (uri === 'console://' && cursor) return route.fulfill({ json: pageOf(uri, [entry('console://reports/', 'Reports', true)]) })
    if (uri === 'console://') return route.fulfill({ json: pageOf(uri, [
      entry('console://summary.txt', 'Summary.txt'),
      entry('console://.cache/', '.cache', true),
      entry('console://.settings', '.settings'),
    ], 'next-folders') })
    if (cursor && failContinuation) return route.fulfill({ status: 502, json: { detail: 'Synthetic unavailable provider' } })
    if (cursor) return route.fulfill({ json: pageOf(uri, [entry('console://reports/final.txt', 'Final report.txt')]) })
    return route.fulfill({ json: pageOf(uri, Array.from({ length: 50 }, (_, n) => entry(`console://reports/report-${n}.txt`, `Report ${n}.txt`)), 'next-reports') })
  })
  await page.route('**/api/file-share/browser/content?*', route => route.fulfill({ contentType: 'text/plain', body: 'Synthetic report preview content' }))
  await mount(page, component, { privileges: ['MEMORY_ACCESS'], dark: width === 390 })
  await expect(page.getByRole('button', { name: 'Browse files for Alice Example', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('file-browser-agents.png'), fullPage: true })
  await selectAgent(page, 'Alice Example')
  if (width === 390) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await page.getByText('Console', { exact: true }).click()
  const main = page.locator('.file-main')
  await expect(main.getByRole('button', { name: 'Open Reports', exact: true })).toBeVisible()
  await expect(page.getByText('.cache', { exact: true })).toHaveCount(0)
  await expect(page.getByText('.settings', { exact: true })).toHaveCount(0)
  await expect(page.locator('.file-tree').getByText('Reports', { exact: true })).toBeInViewport()
  expect(calls.filter(call => call.uri === 'console://' && call.cursor === 'next-folders')).toHaveLength(1)
  await page.screenshot({ path: testInfo.outputPath('file-browser-locations.png'), fullPage: true })
  await main.getByRole('button', { name: 'Open Reports', exact: true }).click()
  await expect(main.getByRole('button', { name: 'Open Report 0.txt', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('file-browser-entries.png'), fullPage: true })
  await expect(page.locator('.file-tree').getByText('Report 0.txt', { exact: true })).toHaveCount(0)
  await main.locator('.file-grid').getByRole('button').last().scrollIntoViewIfNeeded()
  await expect(main.getByRole('alert')).toBeVisible()
  failContinuation = false
  await main.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(main.getByRole('button', { name: 'Open Final report.txt', exact: true })).toBeVisible()
  expect(calls.filter(call => call.cursor === 'next-reports')).toHaveLength(2)
  await expect(main.getByRole('button', { name: 'Open Report 0.txt', exact: true })).toHaveCount(1)
  const final = main.getByRole('button', { name: 'Open Final report.txt', exact: true })
  await final.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByText('Synthetic report preview content', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await main.getByRole('button', { name: 'Parent directory', exact: true }).click()
  await expect(main.getByRole('button', { name: 'Open Reports', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('file-browser.png'), fullPage: true })
})

test('a Galaris document opens its existing modal with the selected agent scope', async ({ page }) => {
  await setup(page)
  await jsonRoute(page, '**/api/file-share/browser/entries?*', pageOf('galaris://', [
    { ...entry('document://doc-a', 'Synthetic document'), media_type: 'text/html' },
  ]))
  const actors = []
  await page.route('**/api/memory/documents/doc-a?*', route => {
    actors.push(new URL(route.request().url()).searchParams.get('agent_id'))
    return route.fulfill({ json: { item: { ...document, title: 'Synthetic document' } } })
  })
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments?*', [])
  await jsonRoute(page, '**/api/memory/documents/doc-a/content/revisions?*', { items: [], total: 0 })
  await mount(page, component, { privileges: ['MEMORY_ACCESS'] })
  await selectAgent(page, 'Alice Example')
  await page.getByText('Galaris', { exact: true }).click()
  await page.locator('.file-main').getByRole('button', { name: 'Open Synthetic document', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Initial body', { exact: true })).toBeVisible()
  expect(actors).toContain('7')
  await page.locator('.q-dialog__backdrop').last().click({ position: { x: 5, y: 5 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('agent changes discard late responses and browsable scheme accordions reopen with empty states', async ({ page }, testInfo) => {
  await setup(page)
  let failMail = true
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/file-share/browser/entries?*', async route => {
    const params = new URL(route.request().url()).searchParams
    if (params.get('uri') === 'mail://' && failMail) return route.fulfill({ status: 502, json: { detail: 'Synthetic unavailable mail provider' } })
    if (params.get('agent_id') === '7') {
      await pending
      return route.fulfill({ json: pageOf('console://', [entry('console://private.txt', 'Alice private.txt')]) }).catch(() => {})
    }
    return route.fulfill({ json: pageOf('console://', [
      entry('console://.cache/', '.cache', true), entry('console://.settings', '.settings'),
    ]) })
  })
  await mount(page, component, { privileges: ['MEMORY_ACCESS'] })
  await selectAgent(page, 'Alice Example')
  const requested = page.waitForRequest(request => request.url().includes('/browser/entries'))
  await page.getByText('Console', { exact: true }).click()
  await requested
  await selectAgent(page, 'Bob Example')
  release()
  await page.getByText('Console', { exact: true }).click()
  await expect(page.getByText('This directory is empty.', { exact: true })).toBeVisible()
  const consoleHeader = page.getByRole('button', { name: 'Console', exact: true })
  await expect(consoleHeader).toHaveAttribute('aria-expanded', 'true')
  await page.screenshot({ path: testInfo.outputPath('file-browser-empty.png'), fullPage: true })
  await consoleHeader.focus()
  await page.keyboard.press('Enter')
  await expect(consoleHeader).toHaveAttribute('aria-expanded', 'false')
  await page.keyboard.press('Enter')
  await expect(consoleHeader).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('Alice private.txt', { exact: true })).toHaveCount(0)
  for (const scheme of ['Messenger', 'HTTPS']) {
    await expect(page.getByRole('button', { name: scheme, exact: true })).toHaveCount(0)
  }
  await page.getByText('Mail', { exact: true }).click()
  const main = page.locator('.file-main')
  await expect(main.getByRole('alert')).toBeVisible()
  await expect(main.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('file-browser-mail-error.png'), fullPage: true })
  failMail = false
  await main.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(main.getByText('This directory is empty.', { exact: true })).toBeVisible()
  await expect(main.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Clear', exact: true })).toHaveCount(0)
  await expect(page.getByRole('combobox')).toHaveValue('Bob Example')
})
