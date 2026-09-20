import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { document as testDocument, agent } from './data.mjs'

test.use({ permissions: ['microphone'], launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] } })

function silentAudio() {
  const wav = Buffer.alloc(44 + 32000)
  wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8)
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22)
  wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34)
  wav.write('data', 36); wav.writeUInt32LE(32000, 40)
  return wav
}

async function controls(page, props = {}, html = '<p>Document</p>', simple = false) {
  if (simple) {
    await mount(page, 'core/util/components/RichTextEditor.vue', {
      props: { modelValue: html, readonly: props.editable === false }, privileges: [],
    })
  } else {
    await jsonRoute(page, '**/api/agents?*', [agent])
    await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice' }], users: [] })
    await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
    await jsonRoute(page, '**/api/memory/documents/folders?*', [{ path: 'Reports', kind: 'custom', shared: false }])
    await jsonRoute(page, '**/api/memory/documents/*/attachments?*', [])
    let current = { ...testDocument, payload: { text: html } }
    await page.route('**/api/memory/items/*?*', route => {
      current.id = new URL(route.request().url()).pathname.split('/').at(-1)
      if (route.request().method() !== 'GET') current = { ...current, ...route.request().postDataJSON(), revision: current.revision + 1 }
      return route.fulfill({ json: current })
    })
    await mount(page, 'app/memory/components/DocumentEditor.vue', {
      props: { documentId: 'doc-a', agentId: 7, editable: true, ...props },
      privileges: props.editable === false ? ['MEMORY_ACCESS'] : ['MEMORY_EDIT', 'MEMORY_ACCESS'],
    })
  }
  await expect(page.locator('.ck-editor__editable')).toBeVisible()
  await page.evaluate(() => {
    const acquire = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    window.dictationTracks = []
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await acquire(constraints)
      window.dictationTracks.push(...stream.getTracks())
      return stream
    }
  })
}

for (const simple of [false, true]) test(`dictation writes live at the cursor without duplicating snapshots and releases the microphone (simple=${simple})`, async ({ page }) => {
  let requests = 0
  await page.route('**/api/llm/me/transcription', route => {
    expect(route.request().headers()['content-type']).toContain('multipart/form-data')
    requests += 1
    return route.fulfill({ json: { text: requests === 1 ? 'spoken words' : requests === 2 ? 'Spoken words, and more.' : 'Spoken words, and more. Elsewhere.' } })
  })
  await controls(page, {}, '<p>Document</p>', simple)
  if (simple) await page.setViewportSize({ width: 390, height: 844 })
  const editor = page.locator('.ck-editor__editable')
  await editor.click()
  await page.keyboard.press('Home')
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await page.getByRole('button', { name: 'Dictate', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.dictationTracks.length)).toBeGreaterThan(0)
  await expect(editor).toHaveText('Doc spoken words ument')
  if (simple) await page.setViewportSize({ width: 1024, height: 900 })
  await expect(page.getByRole('button', { name: 'Finish dictation' })).toBeEnabled()
  await expect(editor).toHaveText('Doc spoken words and more. ument')
  await page.keyboard.press('Control+End')
  await expect(editor).toHaveText('Doc spoken words and more. ument Elsewhere.')
  await page.getByRole('button', { name: 'Finish dictation' }).click()
  await expect.poll(() => page.evaluate(() => window.dictationTracks.every(track => track.readyState === 'ended'))).toBe(true)
  await expect(page.getByRole('button', { name: 'Dictate', exact: true })).toBeEnabled()
  await expect(editor).toHaveText('Doc spoken words and more. ument Elsewhere.')
})

for (const simple of [false, true]) test(`a late dictation response cannot insert into another text (simple=${simple})`, async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  let requested = false
  await page.route('**/api/llm/me/transcription', async route => {
    requested = true
    await pending
    await route.fulfill({ json: { text: 'Old document dictation.' } })
  })
  await controls(page, {}, '<p>Document</p>', simple)
  try {
    await page.getByRole('button', { name: 'Dictate', exact: true }).click()
    await expect.poll(() => requested).toBe(true)
    await page.evaluate(simple => window.testApp.setProps(simple ? { modelValue: '<p>Other text</p>' } : { documentId: 'doc-b' }), simple)
  } finally { release() }
  await expect(page.locator('.ck-editor__editable')).toHaveText(simple ? 'Other text' : 'Document')
  await expect.poll(() => page.evaluate(() => window.dictationTracks.every(track => track.readyState === 'ended'))).toBe(true)
})

test('read-only documents can read and cancel pending speech without dictation', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  let requested = false
  await page.route('**/api/llm/me/speech', async route => {
    expect(route.request().postDataJSON()).toEqual({ html: '<p>Document</p>', offset: 0 })
    requested = true
    await pending
    await route.fulfill({ status: 502, json: { detail: 'Cancelled provider response' } })
  })
  await controls(page, { editable: false })
  await page.setViewportSize({ width: 390, height: 844 })
  try {
    await expect(page.getByRole('button', { name: 'Dictate', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Read text' }).click()
    await expect.poll(() => requested).toBe(true)
    await expect(page.getByRole('button', { name: 'Stop reading' })).not.toBeVisible()
    await page.getByRole('button', { name: 'Reading controls', exact: true }).click()
    await page.getByRole('button', { name: 'Stop reading' }).click()
  } finally { release() }
  await expect(page.getByRole('button', { name: 'Read text' })).toBeEnabled()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

for (const simple of [false, true]) for (const editable of [true, false]) test(`reading uses only the selected passage, or all text without a selection (simple=${simple}, editable=${editable})`, async ({ page }) => {
  const requests = []
  await page.route('**/api/llm/me/speech', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ body: silentAudio(), contentType: 'audio/wav', headers: { 'X-Next-Offset': String(route.request().postDataJSON().offset + 20), 'X-Speech-Done': 'false' } })
  })
  await controls(page, { editable }, '<p>Avant <strong>premier passage</strong></p><p>second passage après</p>', simple)
  if (!editable) await expect(page.getByRole('button', { name: 'Dictate', exact: true })).toHaveCount(0)
  if (simple) await expect(page.getByRole('button', { name: 'Full width', exact: true })).toHaveCount(0)
  const editor = page.locator('.ck-editor__editable')
  await editor.evaluate(element => {
    const paragraphs = element.querySelectorAll('p')
    const range = document.createRange()
    range.setStart(paragraphs[0].querySelector('strong').firstChild, 3)
    range.setEnd(paragraphs[1].firstChild, 6)
    window.getSelection().removeAllRanges()
    window.getSelection().addRange(range)
  })
  await expect.poll(() => page.evaluate(() => window.getSelection().toString())).toContain('mier passage')
  await page.getByRole('button', { name: 'Read text', exact: true }).click()
  await expect.poll(() => requests.length).toBeGreaterThan(0)
  const selected = await page.evaluate(html => {
    const fragment = new DOMParser().parseFromString(html, 'text/html')
    return [...fragment.body.children].map(block => block.textContent)
  }, requests[0].html)
  expect(selected).toEqual(['mier passage', 'second'])
  // A later selection change must not alter the snapshot used for subsequent chunks.
  await page.keyboard.press('Escape')
  await editor.evaluate(element => {
    window.getSelection().collapse(element.querySelector('p').firstChild, 0)
  })
  await expect.poll(() => requests.length).toBeGreaterThan(1)
  expect(requests[1]).toEqual({ html: requests[0].html, offset: 20 })
  await page.getByRole('button', { name: 'Reading controls', exact: true }).click()
  await page.getByRole('button', { name: 'Stop reading' }).click()
  requests.length = 0
  await page.getByRole('button', { name: 'Read text', exact: true }).click()
  await expect.poll(() => requests.length).toBeGreaterThan(0)
  expect(requests[0].html).toContain('Avant ')
  expect(requests[0].html).toContain('second passage après')
  await page.getByRole('button', { name: 'Reading controls', exact: true }).click()
  await page.getByRole('button', { name: 'Stop reading' }).click()
})

test('My profile saves the selected profile and voice without administrative privileges', async ({ page }) => {
  await jsonRoute(page, '**/api/auth/mfa/status', { enabled: false, setup_pending: false, recovery_codes_remaining: 0 })
  await jsonRoute(page, '**/api/llm/me/options', { profiles: [{ id: 7, label: 'Personal profile' }], current_profile_id: 7, voices: [{ id: 9, label: 'My voice' }], native_voices: [] })
  let saved
  await page.route('**/api/llm/me/preferences', route => {
    if (route.request().method() === 'PUT') saved = route.request().postDataJSON()
    return route.fulfill({ json: saved ?? { profile_id: null, voice_llm_id: null, voice_mode: 'tts', voice_code: null } })
  })
  await mount(page, 'core/authorize/pages/profile.vue')
  await page.getByLabel('LLM profile', { exact: true }).click()
  await page.getByRole('option', { name: 'Personal profile', exact: true }).click()
  await page.getByLabel('Voice / TTS', { exact: true }).click()
  await page.getByRole('option', { name: 'My voice', exact: true }).click()
  await page.getByRole('form', { name: 'Models', exact: true }).getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => saved).toEqual({ profile_id: 7, voice_llm_id: 9, voice_mode: 'tts', voice_code: null })
  await expect(page.getByRole('status')).toHaveText('Preferences saved.')
})

test('the user form saves native model and voice choices for the selected user', async ({ page }) => {
  const initial = { profile_id: 7, voice_llm_id: 9, voice_mode: 'tts', voice_code: null }
  await jsonRoute(page, '**/api/llm/me/options', {
    profiles: [{ id: 7, label: 'Personal profile' }], current_profile_id: 7,
    voices: [{ id: 9, label: 'My voice' }],
    native_voices: [{ model_id: 11, voice_code: 'voice:alloy', label: 'Alloy', caption: 'Provider · Realtime model' }],
  })
  let saved
  await page.route('**/api/llm/users/42/preferences', route => {
    if (route.request().method() === 'PUT') saved = route.request().postDataJSON()
    return route.fulfill({ json: saved ?? initial })
  })
  await mount(page, 'core/user/components/UserAdminForm.vue', {
    props: { user: { id: 42, email: 'other@example.test', display_name: 'Other user', is_active: true } },
    privileges: ['UPDATE_USER'],
  })
  await page.getByRole('tab', { name: 'Models', exact: true }).click()
  await page.getByLabel('LLM profile', { exact: true }).click()
  await page.getByRole('option', { name: 'Current profile — Personal profile', exact: true }).click()
  await page.getByLabel('Voice / TTS', { exact: true }).click()
  await page.getByRole('option', { name: /Alloy/ }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => saved).toEqual({ profile_id: null, voice_llm_id: 11, voice_mode: 'realtime', voice_code: 'voice:alloy' })
  // Reopening the real form must reflect the persisted selection.
  await page.getByRole('tab', { name: /Edit user/i }).click()
  await page.getByRole('tab', { name: 'Models', exact: true }).click()
  await expect(page.getByLabel('Voice / TTS', { exact: true })).toHaveValue('Alloy')
})

test('dictation enters the real editor as escaped text and autosaves without losing existing content', async ({ page }) => {
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice' }], users: [] })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await jsonRoute(page, '**/api/memory/documents/folders?*', [{ path: 'Reports', kind: 'custom', shared: false }])
  await jsonRoute(page, '**/api/memory/documents/doc-a/attachments?*', [])
  await jsonRoute(page, '**/api/llm/me/transcription', { text: 'Hello <script>alert(1)</script> & goodbye.' })
  const updates = []
  const initial = { ...testDocument, payload: { text: '<p>Existing content.</p>' } }
  await page.route('**/api/memory/items/doc-a?*', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: initial })
    const update = route.request().postDataJSON()
    updates.push(update)
    return route.fulfill({ json: { ...initial, ...update, revision: 4, lock_version: 4 } })
  })
  await mount(page, 'app/memory/components/DocumentEditor.vue', {
    props: { documentId: 'doc-a', agentId: 7, editable: true }, privileges: ['MEMORY_EDIT', 'MEMORY_ACCESS'],
  })
  const editor = page.locator('.ck-editor__editable[contenteditable="true"]')
  await expect(editor).toContainText('Existing content.')
  await editor.click()
  await page.keyboard.press('Control+End')
  await page.getByRole('button', { name: 'Dictate', exact: true }).click()
  await expect(editor).toContainText('Hello <script>alert(1)</script> & goodbye.')
  await page.getByRole('button', { name: 'Finish dictation' }).click()
  await expect.poll(() => updates.length).toBe(1)
  expect(updates[0].payload.text).toContain('Existing content.')
  expect(updates[0].payload.text).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
  expect(updates[0].payload.text).not.toContain('<script>')
  expect(updates[0].expected_revision).toBe(3)
  await expect(editor).toContainText('Hello <script>alert(1)</script> & goodbye.')
})

test('reading pauses, resumes at the same position, plays successive chunks and stops', async ({ page }) => {
  const wav = silentAudio()
  const offsets = []
  await page.route('**/api/llm/me/speech', route => {
    const { offset } = route.request().postDataJSON()
    offsets.push(offset)
    return route.fulfill({ body: wav, contentType: 'audio/wav', headers: { 'X-Next-Offset': String(offset + 2000), 'X-Speech-Done': 'false' } })
  })
  await controls(page)
  await page.getByRole('button', { name: 'Reading controls', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeDisabled()
  expect(offsets).toEqual([])
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Read text' }).click()
  await expect.poll(() => page.locator('audio[hidden]').evaluate(audio => audio.currentTime)).toBeGreaterThan(0.1)
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).not.toBeVisible()
  await page.getByRole('button', { name: 'Reading controls', exact: true }).click()
  await page.getByRole('button', { name: 'Pause', exact: true }).click()
  const position = await page.locator('audio[hidden]').evaluate(audio => audio.currentTime)
  await expect.poll(() => page.locator('audio[hidden]').evaluate(audio => audio.paused)).toBe(true)
  await page.getByRole('button', { name: 'Reading controls', exact: true }).click()
  expect(await page.locator('audio[hidden]').evaluate(audio => audio.currentTime)).toBe(position)
  await page.getByRole('button', { name: 'Resume', exact: true }).click()
  await expect.poll(() => offsets.length).toBe(2)
  await expect.poll(() => page.locator('audio[hidden]').evaluate(audio => !audio.paused)).toBe(true)
  await page.getByRole('button', { name: 'Reading controls', exact: true }).click()
  await page.getByRole('button', { name: 'Stop reading' }).click()
  await expect(page.locator('audio[hidden]')).not.toHaveAttribute('src')
  await expect.poll(() => page.locator('audio[hidden]').evaluate(audio => audio.paused)).toBe(true)
})

test('pausing during synthesis keeps incoming audio paused until Resume', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  let requested = false
  await page.route('**/api/llm/me/speech', async route => {
    requested = true
    await pending
    await route.fulfill({ body: silentAudio(), contentType: 'audio/wav', headers: { 'X-Next-Offset': '8', 'X-Speech-Done': 'true' } })
  })
  await controls(page)
  try {
    await page.getByRole('button', { name: 'Read text' }).click()
    await expect.poll(() => requested).toBe(true)
    await page.getByRole('button', { name: 'Reading text', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Resume', exact: true })).not.toBeVisible()
  } finally { release() }
  const audio = page.locator('audio[hidden]')
  await expect(audio).toHaveAttribute('src', /^blob:/)
  expect(await audio.evaluate(audio => ({ paused: audio.paused, time: audio.currentTime }))).toEqual({ paused: true, time: 0 })
  await page.getByRole('button', { name: 'Reading paused', exact: true }).click()
  await expect.poll(() => audio.evaluate(audio => audio.currentTime)).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Reading controls', exact: true }).click()
  await page.getByRole('button', { name: 'Stop reading' }).click()
  await expect(audio).not.toHaveAttribute('src')
})
