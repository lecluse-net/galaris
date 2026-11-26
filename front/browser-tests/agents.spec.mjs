import { test, expect, mount, jsonRoute, selectDocumentContext } from './fixtures.mjs'
import { agent } from './data.mjs'

async function agentFixtures(page) {
  await jsonRoute(page, '**/api/agents/avatar-generation', { available: false })
  await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: 'hermes', is_owner: true }])
  await jsonRoute(page, '**/api/agents/titles?*', [])
  await jsonRoute(page, '**/api/agents/groups?*', [])
  await jsonRoute(page, '**/api/agents/drivers', [{ name: 'hermes', label: 'Hermes', manages_runtime: true }])
  await jsonRoute(page, '**/api/harnesses/agents/7', { containerized: true })
}

const embeddedDrivers = available => [
  { name: 'internal', label_key: 'agent.harnessInternal', transport: 'embedded', available: true, manages_runtime: false },
  { name: 'claude_embedded', label_key: 'agent.harnessClaudeEmbedded', transport: 'embedded', available, manages_runtime: false },
]

for (const width of [1440, 390]) test(`an agent citation switches to an avatar card and survives saving and reading (${width}px)`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  await agentFixtures(page)
  await jsonRoute(page, '**/api/agents/7', agent)
  await jsonRoute(page, '**/api/harnesses/agents/7/status', { status: 'stopped', managed: false, containerized: false, capabilities: [], available_actions: [] })
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP8/x8AAwMCAHwG0LwAAAAASUVORK5CYII=', 'base64')
  await page.route('**/api/agents/7/avatar?*', route => route.fulfill({ contentType: 'image/png', body: png }))
  await mount(page, 'core/util/components/RichTextEditor.vue', { privileges: ['AGENT_ACCESS'] })
  await page.evaluate(async () => {
    const { richLinkCard } = await import('/core/util/richText.ts')
    await window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
      profile: 'document', modelValue: '<p><a href="galaris://agent/7">Alice Example</a></p>',
      createLinkCard: uri => richLinkCard(uri, null),
    } })
  })
  const editor = page.locator('[data-editor-surface]')
  await selectDocumentContext(page, editor.getByRole('link', { name: 'Alice Example', exact: true }))
  await page.getByRole('toolbar', { name: 'Contextual actions' }).getByRole('button', { name: 'Show card', exact: true }).click()
  const card = editor.locator('.galaris-agent-card')
  await expect(card).toContainText(agent.job_title)
  await expect(card.locator('img')).toHaveJSProperty('naturalWidth', 1)
  await card.screenshot({ path: testInfo.outputPath('agent-citation-card.png') })
  await card.locator('p a').click({ modifiers: ['Control'] })
  await expect(page.getByRole('dialog').locator('.agent-card')).toContainText('Alice Example')
  await page.keyboard.press('Escape')
  await card.locator('.agent-citation-avatar').click({ modifiers: ['Control'] })
  await expect(page.getByRole('dialog').locator('.agent-card')).toContainText('Alice Example')
  await page.keyboard.press('Escape')
  await selectDocumentContext(page, card.getByText(agent.job_title, { exact: true }))
  await page.getByRole('toolbar', { name: 'Contextual actions' }).getByRole('button', { name: 'Show URL', exact: true }).click()
  await expect(card).toHaveCount(0)
  await selectDocumentContext(page, editor.getByRole('link', { name: 'Alice Example', exact: true }))
  await page.getByRole('toolbar', { name: 'Contextual actions' }).getByRole('button', { name: 'Show card', exact: true }).click()
  await expect(card).toHaveCount(1)
  const source = await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1).value)
  expect(source).toContain('galaris-agent-card'); expect(source).toContain('galaris://agent/7')
  expect(source).not.toContain('blob:'); expect(source).not.toContain('galaris-resource-embed')
  await mount(page, 'core/util/components/RichText.vue', { props: { content: source, profile: 'document' }, privileges: ['AGENT_ACCESS'] })
  await expect(page.locator('.galaris-agent-card img')).toHaveJSProperty('naturalWidth', 1)
  await page.locator('.agent-citation-avatar').click()
  await expect(page.getByRole('dialog').locator('.agent-card')).toBeVisible()
  await page.keyboard.press('Escape')
  await page.locator('.galaris-agent-card p a').click()
  await expect(page.getByRole('dialog').locator('.agent-card')).toBeVisible()
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: source, profile: 'document', readonly: true }, privileges: ['AGENT_ACCESS'] })
  await page.locator('.agent-citation-avatar').click()
  await expect(page.getByRole('dialog').locator('.agent-card')).toBeVisible()
  await page.keyboard.press('Escape')
  await page.locator('.galaris-agent-card p a').click()
  await expect(page.getByRole('dialog').locator('.agent-card')).toBeVisible()
})

for (const source of ['file', 'citation']) for (const width of [1440, 390]) test(`an agent ${source} opens its card and keeps its management actions in the modal (${width}px)`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  await agentFixtures(page)
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  await jsonRoute(page, '**/api/harnesses/catalog?*', [])
  await page.route('**/api/agents/7/avatar?*', route => route.fulfill({ status: 404 }))
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'galaris', label: 'Galaris', capabilities: ['list', 'read', 'info'], native: true }])
  const file = { uri: 'galaris://agent/7', name: '7.json', metadata: { label: 'Alice Example' }, is_collection: false, media_type: 'application/json', size: null, capabilities: ['read', 'info'] }
  let deleted = false, denied = true, reads = 0
  let catalogueReads = 0
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/agents') catalogueReads++
  })
  await page.route('**/api/documents/doc-a/internal-attachments?*', route => route.fulfill({ json: { items: deleted ? [] : [{ ...file, available: true }], lock_version: 1 } }))
  await page.route('**/api/agents/7', route => {
    if (route.request().method() === 'DELETE') { deleted = true; return route.fulfill({ status: 204 }) }
    reads++
    return route.fulfill(denied ? { status: 403, json: { detail: 'Synthetic denied agent' } } : { json: { ...agent, agent_driver: 'hermes' } })
  })
  await page.route('**/api/file-share/browser/entries?*', route => route.fulfill({ json: { entries: deleted ? [] : [file], truncated: false, next_cursor: null } }))
  await jsonRoute(page, '**/api/harnesses/agents/7/status', { status: 'running', managed: true, lifecycle_status: 'ready', capabilities: ['restart', 'stop'], available_actions: ['restart', 'stop'], last_error: null })
  let restarts = 0
  await page.route('**/api/harnesses/agents/7/actions/restart', route => { restarts++; return route.fulfill({ json: { status: 'queued', output: '' } }) })
  if (source === 'file') {
    await mount(page, 'app/file_share/components/AgentFileBrowser.vue', { props: { agentId: 7 }, privileges: ['AGENT_EDIT'] })
    if (width < 1024) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
    await page.locator('.file-tree').getByText('Galaris', { exact: true }).click()
  } else await mount(page, 'core/util/components/RichText.vue', { props: { content: '<p><a href="galaris://agent/7">Alice Example</a></p>', profile: 'document' }, privileges: ['AGENT_EDIT'] })
  const open = () => source === 'file' ? page.getByRole('button', { name: 'Open Alice Example', exact: true }).click() : page.getByRole('link', { name: 'Alice Example', exact: true }).click()
  const catalogueReadsBeforePreview = catalogueReads
  await open()
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible()
  denied = false
  await page.getByRole('dialog').getByRole('button', { name: 'Retry', exact: true }).click()
  const card = page.getByRole('dialog').locator('.agent-card')
  await expect(card).toHaveCount(1)
  await expect(card.getByText('Alice Example', { exact: true })).toBeVisible()
  await expect(card.getByText('An agent for testing', { exact: true })).toBeVisible()
  await card.getByRole('button', { name: 'Restart', exact: true }).click()
  await expect.poll(() => restarts).toBe(1)
  await card.getByRole('button', { name: 'Edit agent', exact: true }).click()
  const edit = page.getByRole('dialog').last()
  await expect(edit.getByLabel('First name *', { exact: true })).toHaveValue('Alice')
  expect(catalogueReads).toBe(catalogueReadsBeforePreview)
  await edit.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await page.getByRole('dialog').screenshot({ path: testInfo.outputPath('agent-preview.png') })
  if (width < 1024) await page.keyboard.press('Escape')
  else await page.locator('.q-dialog__backdrop').last().click({ position: { x: 5, y: 5 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await open()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete agent', exact: true }).click()
  await page.getByRole('dialog').last().getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(deleted).toBe(true)
  expect(reads).toBe(3)
})

for (const width of [390, 1440]) {
  test(`avatar generation recovers from errors and keeps late results with their agent (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await agentFixtures(page)
    let available = false
    await page.route('**/api/agents/avatar-generation', route => route.fulfill({ json: { available } }))
    const first = { ...agent, agent_driver: 'internal', updated_at: null }
    const second = { ...first, id: 8, code: 'lyra', first_name: 'Lyra' }
    await page.route('**/api/agents?*', route => route.fulfill({ json: [first, second] }))
    await jsonRoute(page, '**/api/agents/drivers', [{ name: 'internal', manages_runtime: false }])
    await jsonRoute(page, '**/api/agents/managers', [agent.user])
    await jsonRoute(page, '**/api/agents/titles?*', [{ id: 1, label: 'agent_titles.ms', gender: 'F' }])
    await jsonRoute(page, '**/api/harnesses/catalog?*', [])
    await jsonRoute(page, '**/api/harnesses/agents/*', { harness_id: null })
    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP8/x8AAwMCAHwG0LwAAAAASUVORK5CYII=', 'base64')
    await page.route('**/api/agents/7/avatar?*', route => route.fulfill({ contentType: 'image/png', body: png }))
    let calls = 0, release
    const pending = new Promise(resolve => { release = resolve })
    await page.route('**/api/agents/7/avatar/generate', async route => {
      expect(route.request().postDataJSON()).toEqual({ instructions: 'Realistic human portrait, natural light.' })
      calls++
      if (calls === 1) return route.fulfill({ status: 502, json: { detail: 'Synthetic generation failure' } })
      await pending
      first.has_avatar = true
      first.updated_at = '2026-01-01T12:00:00Z'
      return route.fulfill({ json: { status: 'success', registered: true } })
    })
    await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT'] })
    const dialog = page.getByRole('dialog').filter({ has: page.getByLabel('First name *', { exact: true }) })
    const generationDialog = page.getByRole('dialog').filter({ has: page.getByLabel('Generation instructions (optional)', { exact: true }) })
    const instructions = generationDialog.getByLabel('Generation instructions (optional)', { exact: true })
    const submit = generationDialog.getByRole('button', { name: 'Generate avatar', exact: true })
    const close = async () => {
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(dialog).toHaveCount(0)
    }
    const edit = name => page.locator('.agent-card').filter({ has: page.getByText(name, { exact: true }) }).getByRole('button', { name: 'Edit agent', exact: true })
    const generate = dialog.getByRole('button', { name: 'Generate avatar', exact: true })
    await edit('Alice Example').click()
    await expect(generate).toHaveCount(0)
    await close()
    available = true
    await edit('Alice Example').click()
    await expect(generate).toBeEnabled()
    await dialog.getByLabel('First name *', { exact: true }).fill('Draft')
    await expect(generate).toBeDisabled()
    await dialog.getByLabel('First name *', { exact: true }).fill('Alice')
    await generate.click()
    await expect(instructions).toBeFocused()
    await instructions.fill('Discard this draft')
    await generationDialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(generationDialog).toHaveCount(0)
    expect(calls).toBe(0)
    await generate.click()
    await expect(instructions).toHaveValue('')
    await instructions.fill('Realistic human portrait, natural light.')
    await generationDialog.evaluate(element => Promise.all(element.getAnimations({ subtree: true }).map(animation => animation.finished)))
    await testInfo.attach('avatar-instructions-light', { body: await generationDialog.screenshot(), contentType: 'image/png' })
    await page.evaluate(() => window.testApp.dark(true))
    await testInfo.attach('avatar-instructions-dark', { body: await generationDialog.screenshot(), contentType: 'image/png' })
    await submit.click()
    await expect(page.getByText(/Synthetic generation failure/)).toBeVisible()
    await expect(instructions).toHaveValue('Realistic human portrait, natural light.')
    await expect(submit).toBeEnabled()
    try {
      await submit.click()
      await expect.poll(() => calls).toBe(2)
      await expect(submit).toBeDisabled()
      await generationDialog.getByRole('button', { name: 'Close', exact: true }).click()
      await close()
      await edit('Alice Example').click()
      await expect(generate).toBeDisabled()
      if (width === 390) {
        await close()
        await edit('Lyra Example').click()
      }
      release()
      await expect(page.getByText('Avatar generated successfully', { exact: true })).toBeVisible()
      await expect(dialog.getByLabel('First name *', { exact: true })).toHaveValue(width === 390 ? 'Lyra' : 'Alice')
      if (width === 390) await expect(dialog.locator('.agent-dialog-avatar img')).toHaveCount(0)
      else await expect(dialog.locator('.agent-dialog-avatar img')).toHaveJSProperty('naturalWidth', 1)
      await close()
      await edit('Alice Example').click()
      await expect(dialog.locator('.agent-dialog-avatar img')).toHaveJSProperty('naturalWidth', 1)
      await dialog.evaluate(element => Promise.all(element.getAnimations({ subtree: true }).map(animation => animation.finished)))
      await testInfo.attach('generated-avatar', { body: await dialog.screenshot(), contentType: 'image/png' })
    } finally { release() }
  })
}

for (const [mode, width] of [['create', 1440], ['edit', 390]]) {
  test(`agent ${mode} form opens while its selectors are still loading (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await agentFixtures(page)
    await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: 'internal' }])
    await jsonRoute(page, '**/api/agents/drivers', [{ name: 'internal', manages_runtime: false }])
    await jsonRoute(page, '**/api/agents/titles?*', [{ id: 1, label: 'agent_titles.ms', gender: 'F' }])
    const pending = []
    for (const [url, json] of [
      ['**/api/agents/managers', [agent.user]],
      ['**/api/harnesses/catalog?*', []],
      ['**/api/harnesses/agents/7', { harness_id: null }],
    ]) {
      await page.route(url, async route => {
        await new Promise(resolve => pending.push(resolve))
        await route.fulfill({ json })
      })
    }
    const writes = []
    await page.route('**/api/agents/7', route => {
      const data = route.request().postDataJSON()
      writes.push(data)
      return route.fulfill({ json: { ...agent, ...data, agent_driver: 'internal' } })
    })
    await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT'] })
    await expect(page.getByText('Alice Example', { exact: true }).first()).toBeVisible()
    try {
      const started = Date.now()
      await page.getByRole('button', { name: mode === 'create' ? 'New Agent' : 'Edit agent', exact: true }).click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      await testInfo.attach('opening-latency', { body: JSON.stringify({ mode, width, milliseconds: Date.now() - started, selectorsPending: pending.length }), contentType: 'application/json' })
      await dialog.getByLabel('First name *', { exact: true }).fill('Lyra')
      await expect.poll(() => pending.length).toBe(mode === 'create' ? 1 : 3)
      pending.splice(0).forEach(resolve => resolve())
      await expect(dialog.getByLabel('Human manager *', { exact: true })).toHaveValue(/Test User/)
      await expect(dialog.getByLabel('First name *', { exact: true })).toHaveValue('Lyra')
      if (mode === 'edit') {
        await testInfo.attach('agent-form', { body: await dialog.screenshot(), contentType: 'image/png' })
        await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
        await expect(dialog).toHaveCount(0)
        expect(writes).toMatchObject([{ first_name: 'Lyra', user_id: 1, title_id: 1 }])
      } else {
        await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
        await expect(dialog).toHaveCount(0)
      }
    } finally { pending.splice(0).forEach(resolve => resolve()) }
  })
}

test('reopening another agent ignores a late harness selection and retries a failed catalogue', async ({ page }) => {
  await agentFixtures(page)
  const second = { ...agent, id: 8, code: 'lyra', first_name: 'Lyra', agent_driver: 'internal' }
  await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: 'internal' }, second])
  await jsonRoute(page, '**/api/agents/drivers', [{ name: 'internal', manages_runtime: false }])
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  let failCatalogue = false
  await page.route('**/api/harnesses/catalog?*', route => route.fulfill(failCatalogue
    ? { status: 503, json: { detail: 'Synthetic catalogue failure' } }
    : { json: [{ id: 'old', name: 'Old Harness' }, { id: 'current', name: 'Current Harness' }] }))
  let release, started = false
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/harnesses/agents/7', async route => {
    started = true
    await pending
    await route.fulfill({ json: { harness_id: 'old' } })
  })
  await jsonRoute(page, '**/api/harnesses/agents/8', { harness_id: 'current' })
  await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT'] })
  const dialog = page.getByRole('dialog')
  const edit = name => page.locator('.agent-card').filter({ has: page.getByText(name, { exact: true }) }).getByRole('button', { name: 'Edit agent', exact: true })
  try {
    await edit('Alice Example').click()
    await expect(dialog).toBeVisible()
    await expect.poll(() => started).toBe(true)
    await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await expect(dialog).toHaveCount(0)
    await edit('Lyra Example').click()
    await expect(dialog.getByLabel('Harness', { exact: true })).toHaveValue('Current Harness')
    const lateResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/harnesses/agents/7')
    release()
    await (await lateResponse).finished()
    await dialog.getByLabel('First name *', { exact: true }).fill('Lyra edited')
    await expect(dialog.getByLabel('Harness', { exact: true })).toHaveValue('Current Harness')
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    failCatalogue = true
    await edit('Lyra Example').click()
    await expect(dialog.getByLabel('First name *', { exact: true })).toHaveValue('Lyra')
    await expect(page.getByText('Unable to load Harnesses.', { exact: true })).toBeVisible()
    // A disabled Quasar select exposes its state on the field rather than an input.
    await expect(dialog.locator('label').filter({ has: page.getByText('Harness', { exact: true }) }))
      .toHaveAttribute('aria-disabled', 'true')
    await expect(page.getByRole('option')).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    failCatalogue = false
    await edit('Lyra Example').click()
    await expect(dialog.getByLabel('Harness', { exact: true })).toHaveValue('Current Harness')
    await expect(dialog.getByLabel('Harness', { exact: true })).toBeEnabled()
  } finally { release() }
})

test('models load on demand without losing the saved profile, voice or identity draft', async ({ page }) => {
  await agentFixtures(page)
  const saved = { ...agent, agent_driver: 'internal', profile_id: 4, fallback_profile_id: 5, voice: 'realtime:12:voice%3Aecho' }
  await jsonRoute(page, '**/api/agents?*', [saved])
  await jsonRoute(page, '**/api/agents/drivers', [{ name: 'internal', manages_runtime: false }])
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  await jsonRoute(page, '**/api/agents/titles?*', [{ id: 1, label: 'agent_titles.ms', gender: 'F' }])
  await jsonRoute(page, '**/api/harnesses/catalog?*', [])
  await jsonRoute(page, '**/api/harnesses/agents/7', { harness_id: null })
  await jsonRoute(page, '**/api/params', { params: [] })
  await jsonRoute(page, '**/api/llm-profiles', { profiles: [{ id: 4, label: 'Saved profile' }, { id: 5, label: 'Backup profile' }], current_profile_id: 4 })
  await jsonRoute(page, '**/api/llm-providers/llms', [{ id: 12, llm_provider_id: 3, service_capabilities: ['realtime_conversation'], label: 'Realtime model', provider_name: 'Synthetic provider' }])
  let release, voiceReads = 0
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/llm-providers/3/resources?*', async route => {
    voiceReads++
    await pending
    await route.fulfill({ json: { models: [{ id: 'voice:echo', name: 'Echo', resource_type: 'voice' }] } })
  })
  const writes = []
  await page.route('**/api/agents/7', route => {
    const data = route.request().postDataJSON()
    writes.push(data)
    return route.fulfill({ json: { ...saved, ...data } })
  })
  await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT', 'LLM_PROFILE_ACCESS', 'LLM_MODEL_ACCESS', 'LLM_PROVIDER_ACCESS'] })
  try {
    await page.getByRole('button', { name: 'Edit agent', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('First name *', { exact: true }).fill('Lyra')
    expect(voiceReads).toBe(0)
    await dialog.getByRole('tab', { name: 'Models', exact: true }).click()
    await expect(dialog.getByLabel('Primary profile', { exact: true })).toHaveValue('Saved profile')
    await expect(dialog.getByLabel('Secondary profile (fallback)', { exact: true })).toHaveValue('Backup profile')
    await expect.poll(() => voiceReads).toBe(1)
    await dialog.getByRole('tab', { name: 'General', exact: true }).click()
    await expect(dialog.getByLabel('First name *', { exact: true })).toHaveValue('Lyra')
    await dialog.getByRole('tab', { name: 'Models', exact: true }).click()
    expect(voiceReads).toBe(1)
    release()
    await expect(dialog.getByLabel('Voice / TTS', { exact: true })).toHaveValue('Echo')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes).toMatchObject([{ first_name: 'Lyra', profile_id: 4, fallback_profile_id: 5, voice: saved.voice }])
    await page.getByRole('button', { name: 'Edit agent', exact: true }).click()
    await dialog.getByRole('tab', { name: 'Models', exact: true }).click()
    const fallback = dialog.getByLabel('Secondary profile (fallback)', { exact: true })
    await expect(fallback).toHaveValue('Backup profile')
    await fallback.click()
    await page.getByRole('option', { name: 'No fallback profile', exact: true }).click()
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes[1]).toMatchObject({ profile_id: 4, fallback_profile_id: null, voice: saved.voice })
  } finally { release() }
})

test('four harness names are unambiguous and Claude saves and reopens', async ({ page }, testInfo) => {
  await agentFixtures(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  const saved = { ...agent, agent_driver: 'internal', is_owner: true }
  let claudeAvailable = true
  const writes = []
  await page.route('**/api/agents?*', route => route.fulfill({ json: [saved] }))
  await page.route('**/api/agents/drivers', route => route.fulfill({ json: embeddedDrivers(claudeAvailable) }))
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  await jsonRoute(page, '**/api/agents/titles?*', [{ id: agent.title_id, label: 'agent_titles.ms', gender: 'F' }])
  await jsonRoute(page, '**/api/harnesses/catalog?*', [
    { id: '98b34442-5102-4392-b348-428c75c7b544', provider_code: 'codex', name: 'Codex', containerized: true },
    { id: 'ae7472cd-7001-488b-b899-d2bcd06d2fa3', provider_code: 'deepseek_harness', name: 'DeepSeek Agent', containerized: true },
  ])
  await jsonRoute(page, '**/api/harnesses/agents/7/status', {
    status: 'internal', managed: false, lifecycle_status: 'internal', capabilities: [], available_actions: [],
  })
  await page.route('**/api/agents/7', route => route.fulfill({ json: saved }))
  await page.route('**/api/harnesses/agents/7', route => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON()
      writes.push(body)
      saved.agent_driver = body.driver_code
    }
    return route.fulfill({ json: {
      harness_id: null, internal: true, driver_code: saved.agent_driver, containerized: false,
      lifecycle_status: saved.agent_driver === 'claude_embedded' && !claudeAvailable ? 'error' : 'ready',
    } })
  })
  await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT'] })
  const edit = page.getByRole('button', { name: 'Edit agent', exact: true })
  const dialog = page.getByRole('dialog').filter({ has: page.getByLabel('First name *', { exact: true }) })
  const selection = dialog.getByLabel('Harness', { exact: true })
  const open = async label => {
    await edit.click()
    await expect(selection).toHaveValue(label)
  }

  await open('Pydantic AI')
  await selection.click()
  await expect(page.getByRole('option')).toHaveCount(4)
  for (const name of ['Pydantic AI', 'Claude Agent', 'DeepSeek Agent', 'Codex']) {
    await expect(page.getByRole('option', { name, exact: true })).toBeVisible()
  }
  await page.getByRole('option', { name: 'Claude Agent', exact: true }).click()
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toEqual([{ driver_code: 'claude_embedded' }])
  await open('Claude Agent')
  await dialog.screenshot({ path: testInfo.outputPath('embedded-claude-desktop.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)

  claudeAvailable = false
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.testApp.dark(true))
  await open('Claude Agent (unavailable)')
  await dialog.screenshot({ path: testInfo.outputPath('embedded-claude-mobile.png'), animations: 'disabled' })
  await selection.click()
  await page.getByRole('option', { name: 'Pydantic AI', exact: true }).click()
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toEqual([{ driver_code: 'claude_embedded' }, { driver_code: 'internal' }])
})

const activeHarnessTask = { id: '00000000-0000-4000-8000-000000000081', label: 'Synthetic active task' }
const pausedHarnessTask = { id: '00000000-0000-4000-8000-000000000082', label: 'Synthetic paused task' }

async function requestEmbeddedHarnessSwitch(page, { active = [], paused = [], inspectionFails = false } = {}) {
  const saved = { ...agent, agent_driver: 'internal' }
  const requests = []
  await agentFixtures(page)
  await jsonRoute(page, '**/api/agents?*', [saved])
  await jsonRoute(page, '**/api/agents/drivers', embeddedDrivers(true))
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  await jsonRoute(page, '**/api/agents/titles?*', [{ id: agent.title_id, label: 'agent_titles.ms', gender: 'F' }])
  await jsonRoute(page, '**/api/harnesses/catalog?*', [])
  const selection = () => ({
    harness_id: null, internal: true, driver_code: saved.agent_driver, containerized: false, lifecycle_status: 'ready',
  })
  await jsonRoute(page, '**/api/harnesses/agents/7/status', {
    status: 'internal', managed: false, lifecycle_status: 'internal', capabilities: [], available_actions: [],
  })
  await page.route('**/api/agents/7', route => {
    if (route.request().method() === 'PUT') requests.push('save')
    return route.fulfill({ json: saved })
  })
  await page.route('**/api/harnesses/agents/7', route => {
    if (route.request().method() === 'PUT') {
      saved.agent_driver = route.request().postDataJSON().driver_code
      requests.push(saved.agent_driver)
    }
    return route.fulfill({ json: selection() })
  })
  await page.route('**/api/harnesses/agents/7/task-blockers', route => {
    requests.push('inspect')
    return inspectionFails
      ? route.fulfill({ status: 503, json: { detail: 'Service unavailable' } })
      : route.fulfill({ json: { active_tasks: active, active_count: active.length, paused_tasks: paused } })
  })
  await page.route('**/api/harnesses/agents/7/task-blockers/terminate-paused', route => {
    requests.push('terminate')
    return route.fulfill({ json: { active_tasks: [], active_count: 0, paused_tasks: [] } })
  })

  await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT', 'TASK_EDIT'] })
  await page.getByRole('button', { name: 'Edit agent', exact: true }).click()
  const editor = page.getByRole('dialog').filter({ has: page.getByLabel('First name *', { exact: true }) })
  const harness = editor.getByLabel('Harness', { exact: true })
  await expect(harness).toHaveValue('Pydantic AI')
  await harness.click()
  await page.getByRole('option', { name: 'Claude Agent', exact: true }).click()
  await editor.getByRole('button', { name: 'Edit', exact: true }).click()
  const confirmation = page.getByRole('dialog').filter({ hasText: 'Tasks are blocking the harness change' })
  const terminate = confirmation.getByRole('button', { name: 'Terminate tasks and continue', exact: true })
  return { editor, confirmation, terminate, requests }
}

for (const paused of [[], [pausedHarnessTask]]) {
  test(`active tasks prevent a harness switch (${paused.length} paused)`, async ({ page }) => {
    const { editor, confirmation, terminate, requests } = await requestEmbeddedHarnessSwitch(page, {
      active: [activeHarnessTask], paused,
    })
    await expect(confirmation.getByText(activeHarnessTask.label, { exact: true })).toBeVisible()
    for (const task of paused) {
      await expect(confirmation.getByText(task.label, { exact: true })).toBeVisible()
    }
    await expect(terminate).toHaveCount(0)
    await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(editor.getByRole('button', { name: 'Edit', exact: true })).toBeEnabled()
    expect(requests).toEqual(['inspect'])
  })
}

test('dismissing a harness switch preserves paused tasks', async ({ page }) => {
  const { editor, confirmation, requests } = await requestEmbeddedHarnessSwitch(page, { paused: [pausedHarnessTask] })
  await expect(confirmation.getByText(pausedHarnessTask.label, { exact: true })).toBeVisible()
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(editor.getByRole('button', { name: 'Edit', exact: true })).toBeEnabled()
  expect(requests).toEqual(['inspect'])
})

test('confirming a harness switch terminates paused tasks before saving', async ({ page }) => {
  const { editor, terminate, requests } = await requestEmbeddedHarnessSwitch(page, { paused: [pausedHarnessTask] })
  await expect(terminate).toBeVisible()
  expect(requests).toEqual(['inspect'])
  await terminate.click()
  await expect(editor).toHaveCount(0)
  expect(requests).toEqual(['inspect', 'terminate', 'save', 'claude_embedded'])
})

test('a harness switch with no blockers saves without termination', async ({ page }) => {
  const { editor, requests } = await requestEmbeddedHarnessSwitch(page)
  await expect(editor).toHaveCount(0)
  expect(requests).toEqual(['inspect', 'save', 'claude_embedded'])
})

test('failed blocker inspection prevents a harness switch', async ({ page }) => {
  const { editor, requests } = await requestEmbeddedHarnessSwitch(page, { inspectionFails: true })
  await expect(page.getByText('Unable to check which tasks are blocking the harness change.')).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Edit', exact: true })).toBeEnabled()
  expect(requests).toEqual(['inspect'])
})

test('reopening agent management refreshes catalogues and reloading retrieves them again', async ({ page }) => {
  await agentFixtures(page)
  const reads = { agents: 0, titles: 0, groups: 0 }
  for (const [key, url] of Object.entries({ agents: '**/api/agents?*', titles: '**/api/agents/titles?*', groups: '**/api/agents/groups?*' })) {
    await page.route(url, route => { reads[key]++; return route.fulfill({ json: [] }) })
  }
  const options = { component: 'app/index/pages/agent.vue', privileges: ['AGENT_EDIT'] }
  await mount(page, options.component, options)
  await expect(page.getByRole('button', { name: 'New Agent', exact: true })).toBeVisible()
  await expect.poll(() => reads).toEqual({ agents: 1, titles: 1, groups: 1 })
  await page.evaluate(async options => {
    window.testApp.unmount()
    await window.testApp.mount(options)
  }, options)
  await expect(page.getByRole('button', { name: 'New Agent', exact: true })).toBeVisible()
  // A new management visit refreshes grants and shared reference data, including empty lists.
  await page.evaluate(async () => {
    const { useAgentStore } = await import('/app/agent/stores/agentStore.ts')
    const store = useAgentStore(window.testApp.pinia)
    await Promise.all([store.fetchAgents(), store.fetchTitles(), store.fetchGroups()])
  })
  expect(reads).toEqual({ agents: 2, titles: 2, groups: 2 })
  await mount(page, options.component, options) // Full navigation, equivalent to F5 for memory caches.
  await expect.poll(() => reads).toEqual({ agents: 3, titles: 3, groups: 3 })
})

test('agent creation requires a first name but accepts an empty last name', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/agents?*', [])
  await jsonRoute(page, '**/api/agents/drivers', embeddedDrivers(true))
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  const titles = Array.from({ length: 500 }, (_, index) => ({ id: index + 1, label: `Synthetic title ${index + 1}`, gender: 'X' }))
  titles.push({ id: 501, label: 'agent_titles.ms', gender: 'F' })
  await page.route('**/api/agents/titles?*', route => {
    const skip = Number(new URL(route.request().url()).searchParams.get('skip') ?? 0)
    return route.fulfill({ json: titles.slice(skip, skip + 500) })
  })
  const saves = []
  await page.route('**/api/agents', route => {
    const data = route.request().postDataJSON()
    saves.push(data)
    if (data.code === 'lyra') {
      return route.fulfill({ status: 400, json: { detail: 'This code is already used by another agent. Please choose a different code.' } })
    }
    return route.fulfill({ status: 201, json: { ...agent, ...data } })
  })
  await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT'] })
  await page.getByRole('button', { name: 'New Agent', exact: true }).click()
  const dialog = page.getByRole('dialog')
  const selection = dialog.getByLabel('Harness', { exact: true })
  await expect(selection).toBeEnabled()
  await selection.click()
  await page.getByRole('option', { name: 'Claude Agent', exact: true }).click()
  await dialog.getByLabel('Agent code', { exact: true }).fill('lyra')
  await dialog.getByLabel('Title *', { exact: true }).click()
  await expect(page.getByRole('option').first()).toBeVisible()
  await page.keyboard.press('End')
  await page.getByRole('option', { name: 'Ms (F)', exact: true }).click()
  await dialog.getByLabel('First name *', { exact: true }).fill('   ')
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(dialog.getByText('First name is required', { exact: true })).toBeVisible()
  expect(saves).toEqual([])
  await dialog.getByLabel('First name *', { exact: true }).fill('Lyra')
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.getByText('This code is already used by another agent. Please choose a different code.', { exact: true })).toBeVisible()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel('First name *', { exact: true })).toHaveValue('Lyra')
  await expect(selection).toHaveValue('Claude Agent')
  await dialog.getByLabel('Agent code', { exact: true }).fill('lyra-available')
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(saves).toHaveLength(2)
  expect(saves[1]).toMatchObject({ code: 'lyra-available', first_name: 'Lyra', last_name: '', title_id: 501, agent_driver: 'claude_embedded' })
})

test('a refreshed portrait survives an older catalogue avatar response', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/harnesses/agents/*/status', { status: 'stopped', managed: false, containerized: false, capabilities: [], available_actions: [] })
  const target = { ...agent, id: 8, code: 'synthetic-portrait', first_name: 'Lyra', last_name: 'Synthetic', agent_driver: 'internal', is_owner: true }
  let catalogue = [{ ...agent, agent_driver: 'internal', has_avatar: true, updated_at: '2026-01-01T12:00:00Z' }, { ...target, has_avatar: false, updated_at: null }]
  await page.route('**/api/agents?*', route => route.fulfill({ json: catalogue }))
  const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP8/x8AAwMCAHwG0LwAAAAASUVORK5CYII=', 'base64')
  let release, started = false
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/agents/7/avatar?*', async route => {
    started = true
    await pending
    await route.fulfill({ contentType: 'image/png', body: image }).catch(() => {})
  })
  await page.route('**/api/agents/8/avatar?*', route => route.fulfill({ contentType: 'image/png', body: image }))
  await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT'] })
  await expect.poll(() => started).toBe(true)
  try {
    const cancelled = page.waitForEvent('requestfailed', request => new URL(request.url()).pathname === '/api/agents/7/avatar')
    catalogue = [{ ...catalogue[0], has_avatar: false, updated_at: '2026-01-01T12:01:00Z' }, { ...target, has_avatar: true, updated_at: '2026-01-01T12:00:00Z' }]
    await page.evaluate(async () => {
      const { invalidateSessionReads } = await import('/core/util/sessionReadCache.ts')
      const { useAgentStore } = await import('/app/agent/stores/agentStore.ts')
      invalidateSessionReads('agent-catalogue')
      await useAgentStore(window.testApp.pinia).fetchAgents()
    })
    const portrait = page.getByRole('img', { name: 'Lyra Synthetic', exact: true })
    await expect(portrait).toBeVisible()
    await expect(portrait).toHaveJSProperty('naturalWidth', 1)
    await cancelled
    release()
    await expect(page.locator('.agent-image-container img')).toHaveCount(1)
    await expect(portrait).toBeVisible()
    await expect(portrait).toHaveJSProperty('naturalWidth', 1)
  } finally { release() }
})

test('built-in titles follow the locale and remain keys until renamed', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/harnesses/agents/7/status', { status: 'running', managed: true, lifecycle_status: 'ready', capabilities: [], available_actions: [], last_error: null })
  await jsonRoute(page, '**/api/agents/titles?*', [
    { id: 1, label: 'agent_titles.ms', gender: 'F' },
    { id: 2, label: 'agent_titles.mr', gender: 'M' },
    { id: 3, label: 'common.save', gender: 'M' },
  ])
  const saves = []
  await page.route('**/api/agents/titles/1', route => {
    const data = route.request().postDataJSON()
    saves.push(data)
    return route.fulfill({ json: { id: 1, ...data } })
  })
  const locale = language => page.evaluate(async language => {
    const { setLocale } = await import('/core/i18n/index.ts')
    setLocale(language)
  }, language)
  await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT', 'AGENT_MANAGE_ALL'] })
  await page.getByRole('tab', { name: 'Titles' }).click()
  await expect(page.getByRole('cell', { name: 'Ms', exact: true })).toBeVisible()
  await locale('fr')
  await expect(page.getByRole('cell', { name: 'Madame', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Monsieur', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'common.save', exact: true })).toBeVisible()
  await page.getByRole('row').filter({ has: page.getByRole('cell', { name: 'Madame', exact: true }) }).getByRole('button').first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('textbox')).toHaveValue('Madame')
  await locale('en')
  await expect(dialog.getByRole('textbox')).toHaveValue('Ms')
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(saves).toEqual([{ label: 'agent_titles.ms', gender: 'F' }])
  await page.getByRole('row').filter({ has: page.getByRole('cell', { name: 'Ms', exact: true }) }).getByRole('button').first().click()
  await expect(dialog.getByRole('textbox')).toHaveValue('Ms')
  await dialog.getByRole('textbox').fill('Doctor')
  await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(saves.at(-1)).toEqual({ label: 'Doctor', gender: 'F' })
  await locale('zh')
  await expect(page.getByRole('cell', { name: 'Doctor', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '先生', exact: true })).toBeVisible()
  await expect(page.getByText('agent_titles.', { exact: false })).toHaveCount(0)
})

test('internal agents remain editable without external runtime supervision', async ({ page }) => {
  await agentFixtures(page)
  await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: 'internal', is_owner: true }])
  await jsonRoute(page, '**/api/agents/drivers', [{ name: 'internal', manages_runtime: false }])
  await jsonRoute(page, '**/api/agents/managers', [agent.user])
  let supervisionReads = 0
  await page.route('**/api/harnesses/agents/7/status', route => {
    supervisionReads++
    return route.fulfill({ status: 503, json: { detail: 'External manager unavailable' } })
  })
  await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT'] })
  await expect(page.getByText('Alice Example', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'New Agent', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  expect(supervisionReads).toBe(0)
  await expect(page.locator('.q-banner').filter({ hasText: /manager/i })).toHaveCount(0)
})

for (const [driver, driverMetadata] of [['hermes', true], ['hermes', false], ['openai_messages', true]]) {
  test(`agent page reports an unavailable manager and recovers for ${driver} with metadata ${driverMetadata}`, async ({ page }) => {
    await page.clock.install()
    await agentFixtures(page)
    if (driver === 'openai_messages') {
      await jsonRoute(page, '**/api/agents?*', [{ ...agent, agent_driver: driver, is_owner: true }])
      await jsonRoute(page, '**/api/agents/drivers', [{ name: driver, manages_runtime: false }])
    }
    if (!driverMetadata) await jsonRoute(page, '**/api/agents/drivers', [])
    await jsonRoute(page, '**/api/harnesses/agents/7/selection', { containerized: true })
    let healthy = false
    await page.route('**/api/harnesses/agents/7/status', route => route.fulfill(healthy
      ? { json: { status: 'running', managed: true, lifecycle_status: 'ready', capabilities: ['restart', 'stop'], available_actions: ['restart', 'stop'], last_error: null } }
      : { status: 503, json: { detail: 'Manager unavailable' } }))
    await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT'] })
    const warning = page.locator('.q-banner').filter({ hasText: /manager/i })
    await expect(warning).toBeVisible()
    healthy = true
    await page.clock.fastForward(5100)
    await expect(warning).toHaveCount(0)
    await expect(page.getByText('Alice Example', { exact: true }).first()).toBeVisible()
  })
}

test('agent runtime restart is sent once and ignores a status read started before the action', async ({ page }) => {
  await page.clock.install()
  await agentFixtures(page)
  const statusUrl = '**/api/harnesses/agents/7/status'
  const running = { status: 'running', managed: true, lifecycle_status: 'ready', capabilities: ['restart', 'stop'], available_actions: ['restart', 'stop'], last_error: null }
  let statusReads = 0
  let releaseStatus, releaseAction
  const oldStatus = new Promise(resolve => { releaseStatus = resolve })
  const pendingAction = new Promise(resolve => { releaseAction = resolve })
  await page.route(statusUrl, async route => {
    if (++statusReads === 2) await oldStatus
    await route.fulfill({ json: running })
  })
  const actions = []
  await page.route('**/api/harnesses/agents/7/actions/restart', async route => {
    actions.push(route.request().method())
    await pendingAction
    await route.fulfill({ json: { status: 'queued', output: '' } })
  })
  await mount(page, 'app/index/pages/agent.vue', { privileges: ['AGENT_EDIT'] })
  const restart = page.getByRole('button', { name: 'Restart', exact: true })
  try {
    await expect(restart).toBeVisible()
    await page.clock.fastForward(5100)
    await expect.poll(() => statusReads).toBe(2)
    await restart.click()
    await expect.poll(() => actions).toEqual(['POST'])
    await restart.click({ force: true })
    expect(actions).toEqual(['POST'])
    releaseAction()
    await expect(restart).toHaveCount(0)
    const obsolete = page.waitForResponse(statusUrl)
    releaseStatus()
    await (await obsolete).finished()
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await expect(restart).toHaveCount(0)
  } finally {
    releaseAction()
    releaseStatus()
  }
})

test('MCP tokens recover a read failure, reveal a new token once and clear it on agent replacement', async ({ page }) => {
  let failed = true, tokens = []
  await page.route('**/api/agents/7/mcp-tokens', route => {
    if (route.request().method() === 'POST') {
      tokens = [{ id: 1, agent_id: 7, label: 'Synthetic client', token: 'masked-token', enabled: true, created_at: '2026-01-01T10:00:00Z' }]
      return route.fulfill({ json: { ...tokens[0], token: 'synthetic-once-only-token' } })
    }
    return route.fulfill(failed ? { status: 503, json: { detail: 'Synthetic token outage' } } : { json: tokens })
  })
  await jsonRoute(page, '**/api/agents/8/mcp-tokens', [])
  await mount(page, 'app/agent/components/AgentMcpPanel.vue', { props: { agent: { id: 7, code: 'synthetic-a' }, canManage: true } })
  const failure = page.getByRole('alert').filter({ hasText: 'Failed to load tokens' })
  await expect(failure).toBeVisible()
  failed = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(failure).toHaveCount(0)
  await page.getByRole('button', { name: 'New token', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('textbox', { name: 'Label (optional)', exact: true }).fill('Synthetic client')
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(dialog.filter({ hasText: 'MCP token created' }).getByRole('textbox')).toHaveValue('synthetic-once-only-token')
  await expect(page.getByRole('cell', { name: 'masked-token', exact: true })).toBeVisible()
  await page.evaluate(() => window.testApp.setProps({ agent: { id: 8, code: 'synthetic-b' } }))
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('cell', { name: 'masked-token', exact: true })).toHaveCount(0)
  expect(await page.locator('input,textarea').evaluateAll(elements => elements.some(element => element.value.includes('synthetic-once-only-token')))).toBe(false)
})
