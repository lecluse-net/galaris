import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const component = 'app/chat/components/InteractionChoice.vue'
const choice = {
  id: 'choice-1', reference: '1A5E4070', title: 'Créer un dossier thématique',
  body: 'Interactions sociales', options: [
    { id: 'create', label: 'Créer ce dossier' },
    { id: 'reject', label: 'Laisser cette activité sans classement' },
  ],
  free_text: false, status: 'PENDING', expires_at: '2099-01-01T00:00:00Z',
  selected_option_id: null, can_answer: true,
}
const resolved = { ...choice, status: 'RESOLVED', selected_option_id: 'create', can_answer: false }
const endpoint = '**/api/chat/rooms/room-1/interactions/choice-1'
const options = { locale: 'fr', props: { roomId: 'room-1', interaction: choice } }
const recordedAnswerStatus = page => page.getByRole('status').filter({ hasText: /^Réponse enregistrée/ })

test('the Chat menu updates the question and unread totals independently', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.clock.install({ time: new Date('2026-10-02T12:00:00Z') })
  await page.addInitScript(() => localStorage.setItem('access_token', 'component-test'))
  await jsonRoute(page, '**/api/chat/status', { enabled: true, chat_enabled: true })
  await jsonRoute(page, '**/api/chat/push/configuration', { available: false })
  let summary = { unread_count: 4, pending_question_count: 2, pending_question_next_expiry: '2026-10-02T12:05:00Z' }
  await page.route('**/api/chat/inbox', route => route.fulfill({ json: summary }))
  await mount(page, 'core/util/components/FolderIcon.vue', {
    route: '/', privileges: ['CHAT_ACCESS'], locale: 'fr', shell: true, dark: false,
  })

  const chat = page.locator('a[href="/chat"]')
  const counters = chat.getByRole('status')
  await expect(counters).toHaveText(['2', '4'])
  await expect(counters.first()).toHaveAccessibleName('2 questions attendent votre réponse')
  await expect(counters.last()).toHaveAccessibleName('4 messages non lus')
  await chat.screenshot({ path: testInfo.outputPath('chat-menu-counters-light.png') })

  await page.evaluate(() => window.testApp.dark(true))
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(chat).not.toBeInViewport()
  await page.getByRole('button', { name: 'Déployer la sidebar', exact: true }).click()
  await expect(chat).toBeInViewport()
  await expect(counters).toHaveText(['2', '4'])
  await page.screenshot({ path: testInfo.outputPath('chat-menu-counters-dark-mobile.png'), animations: 'disabled' })

  summary = { ...summary, unread_count: 0, pending_question_count: 1 }
  await page.evaluate(() => window.testApp.emitSocket('chat.message', { data: { is_new: false } }))
  await expect(counters).toHaveText(['1'])
  await expect(counters.first()).toHaveAccessibleName('Une question attend votre réponse')

  summary = { ...summary, pending_question_count: 0, pending_question_next_expiry: null }
  await page.clock.fastForward('05:00')
  await expect(counters).toHaveCount(0)
})

test('a rich approval body keeps its editorial structure and response controls', async ({ page }, testInfo) => {
  const room = { id: 'room-1', label: 'Conversation synthétique', agent_id: 7, agent_name: 'Agent synthétique',
    agent_active: false, writable: true, members: [], unread_count: 0, conversation_type: 'text' }
  const approvalChoice = { ...choice, title: 'Demande d’autorisation', is_authorization: true,
    body_html: '<h3>Créer un agent</h3><table class="galaris-table-gray galaris-table-minimal"><tbody>'
      + '<tr><th>Prénom</th><td>Camille</td></tr><tr><th>Intitulé du poste</th><td>Relecture &lt;2026&gt;</td></tr>'
      + '<tr><th>Code de l’agent</th><td>relecture-synthetique</td></tr><tr><th>Harnais</th><td>internal</td></tr>'
      + '</tbody></table><p><strong>Fiche de poste</strong></p><h2>Plan du projet</h2><ul><li>Relire le bilan</li></ul>'
      + '<p><strong>Personnalité</strong></p><p>Privilégie les exemples courts et précis.</p>'
      + '<blockquote><p>Cette décision concerne uniquement l’action décrite ici.</p></blockquote>',
    options: [{ id: 'allow', label: 'Autoriser cette action' }, { id: 'deny', label: 'Refuser cette action' }],
  }
  const message = { id: 'approval-message', external_id: 'approval-external', room_id: room.id,
    files: [], is_mine: false, text: choice.body, created_at: '2026-09-18T12:00:00Z',
    sender: { display_name: room.agent_name, is_ai: true },
    interaction: approvalChoice }
  for (const [path, json] of [
    ['status', { enabled: true, chat_enabled: true, max_attachment_bytes: 1000000 }],
    ['rooms?*', { items: [room], total: 1 }],
    ['rooms/room-1', room],
    ['rooms/room-1/messages?*', { items: [message], total: 1 }],
    ['rooms/room-1/activity?*', { items: [], total: 0 }],
    ['rooms/room-1/speech/status*', { available_agent_ids: [] }],
    ['rooms/room-1/read', {}],
    ['rooms/room-1/commands', { commands: [] }],
    ['inbox', { unread_count: 0 }],
    ['emojis/frequent', { items: [] }],
    ['agents/7/avatar', {}],
  ]) await jsonRoute(page, '**/api/chat/' + path, json)
  await mount(page, 'app/chat/pages/index.vue', {
    route: '/chat?room=room-1', privileges: ['CHAT_SEND'], locale: 'fr', shell: true,
  })
  const approval = page.getByRole('region', { name: approvalChoice.title })
  for (const [width, dark] of [[1440, false], [1440, true], [390, true]]) {
    await page.setViewportSize({ width, height: 900 })
    await page.evaluate(value => window.testApp.dark(value), dark)
    await expect(approval.getByRole('heading', { name: 'Créer un agent' })).toBeVisible()
    await expect(approval.getByRole('row', { name: 'Intitulé du poste Relecture <2026>' })).toBeVisible()
    await expect(approval.getByRole('heading', { name: 'Plan du projet' })).toBeVisible()
    await expect(approval.getByRole('listitem')).toHaveText('Relire le bilan')
    await expect(approval.getByRole('button', { name: 'Autoriser cette action' })).toBeEnabled()
    await approval.screenshot({ path: testInfo.outputPath(`rich-approval-${width}-${dark ? 'dark' : 'light'}.png`), animations: 'disabled' })
  }
})

for (const [locale, expected] of [
  ['fr', 'Réponse à « Demande d’autorisation » (#FA12BC34) : Autoriser cette action'],
  ['en', 'Answer to “Demande d’autorisation” (#FA12BC34): Autoriser cette action'],
  ['zh', '对“Demande d’autorisation”的回复 (#FA12BC34)：Autoriser cette action'],
]) {
  test(`recorded answers are displayed in the interface language (${locale})`, async ({ page }) => {
    await jsonRoute(page, '**/api/chat/rooms/*/speech/status*', { available_agent_ids: [] })
    const message = {
      id: 'answer-1', external_id: 'answer-external-1', room_id: 'room-1', direction: 'inbound',
      text: 'Answer to “Demande d’autorisation” (#FA12BC34): Autoriser cette action',
      interaction_answer: { title: 'Demande d’autorisation', reference: 'FA12BC34', answer: 'Autoriser cette action' },
      files: [], is_mine: true, sender: { display_name: 'User', is_ai: false },
      created_at: '2026-09-18T12:00:00Z', interaction: null,
    }
    const props = { roomId: 'room-1', agentId: 7, agentName: 'Alice', activity: [], liveRound: null,
      messages: [message, { ...message, id: 'ordinary', external_id: 'ordinary-external', reply_to: message.external_id, interaction_answer: null, text: 'Message ordinaire conservé.' }],
    }
    await mount(page, 'app/chat/components/MessageTimeline.vue', { locale, props })
    await expect(page.getByText(expected, { exact: true })).toBeVisible()
    await expect(page.getByText('Message ordinaire conservé.', { exact: true })).toBeVisible()
    await expect(page.locator('.reply-preview')).toContainText(expected)
    await page.evaluate(async () => {
      const { setLocale } = await import('/core/i18n/index.ts')
      setLocale('fr')
    })
    await expect(page.getByText('Réponse à « Demande d’autorisation » (#FA12BC34) : Autoriser cette action', { exact: true })).toBeVisible()
    await mount(page, 'app/chat/components/MessageTimeline.vue', { locale, props })
    await expect(page.getByText(expected, { exact: true })).toBeVisible()
    await page.route('**/api/chat/agents/*/avatar', route => route.fulfill({ status: 404 }))
    await mount(page, 'app/chat/components/RoomList.vue', { locale, props: {
      rooms: [{ id: 'room-1', label: 'Synthetic room', agent_id: 7, agent_name: 'Alice',
        unread_count: 0, show_last_message: true, last_message: message }],
      canCreate: false, canImpersonate: false, viewerAgentId: null, viewerAgents: [],
      includeExternal: true, includeArchived: false, hasMore: false, loadingMore: false,
    } })
    await expect(page.getByText(expected, { exact: true })).toBeVisible()
  })
}

test('the conversation displays actionable choices and preserves ordinary text messages', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await jsonRoute(page, '**/api/chat/rooms/*/speech/status*', { available_agent_ids: [] })
  await jsonRoute(page, `${endpoint}/answer`, resolved)
  const message = {
    id: 'message-1', external_id: 'external-1', text: '1. Créer ce dossier\n2. Laisser cette activité sans classement',
    files: [], is_mine: false, sender: { display_name: 'Alice', is_ai: true },
    created_at: '2026-09-18T12:00:00Z', interaction: choice,
  }
  await mount(page, 'app/chat/components/MessageTimeline.vue', { locale: 'fr', props: {
    roomId: 'room-1', agentId: 7, agentName: 'Alice', activity: [], liveRound: null,
    messages: [message, { ...message, id: 'message-2', interaction: null, text: 'Message ordinaire conservé.' }],
  } })
  const create = page.getByRole('button', { name: 'Créer ce dossier' })
  await expect(create).toBeVisible()
  await expect(page.getByText('Interactions sociales', { exact: true })).toBeVisible()
  await expect(page.getByText('Message ordinaire conservé.', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('choices-mobile.png'), fullPage: true })
  await create.click()
  await expect(recordedAnswerStatus(page)).toHaveText('Réponse enregistrée.')
  await expect(create).toHaveAttribute('aria-pressed', 'true')
})

test('a recorded authorization keeps only its chosen button through refresh and reopening', async ({ page }) => {
  const pendingAuthorization = { ...choice, is_authorization: true }
  const resolvedAuthorization = { ...resolved, is_authorization: true }
  let release
  const ready = new Promise(resolve => { release = resolve })
  const submissions = []
  await page.route(`${endpoint}/answer`, async route => {
    submissions.push(route.request().postDataJSON())
    await ready
    await route.fulfill({ json: resolvedAuthorization })
  })
  await mount(page, component, { ...options, props: { ...options.props, interaction: pendingAuthorization } })
  const create = page.getByRole('button', { name: 'Créer ce dossier' })
  const reject = page.getByRole('button', { name: 'Laisser cette activité sans classement' })
  await create.click()
  await expect.poll(() => submissions).toEqual([{ option_id: 'create' }])
  await expect(create).toBeDisabled()
  await expect(reject).toBeDisabled()
  release()
  const acknowledgement = recordedAnswerStatus(page)
  await expect(acknowledgement).toHaveText('Réponse enregistrée.')
  await expect(create).toHaveAttribute('aria-pressed', 'true')
  await expect(reject).toHaveCount(0)
  // A history request started before the click may return the old pending snapshot.
  await page.evaluate(interaction => window.testApp.setProps({ interaction }), pendingAuthorization)
  await expect(create).toBeDisabled()
  await mount(page, component, { ...options, props: { ...options.props, interaction: resolvedAuthorization } })
  await expect(acknowledgement).toHaveText('Réponse enregistrée.')
  await expect(create).toBeDisabled()
  await expect(reject).toHaveCount(0)
  expect(submissions).toHaveLength(1)
})

test('expired and read-only choices cannot be submitted', async ({ page }) => {
  await mount(page, component, { ...options, props: { ...options.props, readonly: true } })
  await expect(page.getByRole('button').first()).toBeDisabled()
  await page.evaluate(interaction => window.testApp.setProps({ readonly: false, interaction }), {
    ...choice, expires_at: '2000-01-01T00:00:00Z',
  })
  await expect(page.getByRole('status').filter({ hasText: /^Cette demande a expiré/ })).toHaveText('Cette demande a expiré.')
  await expect(page.getByRole('button').first()).toBeDisabled()
})

test('a lost response reloads the recorded decision before enabling another answer', async ({ page }) => {
  await page.route(`${endpoint}/answer`, route => route.fulfill({ status: 503, json: { detail: 'Lost response' } }))
  await jsonRoute(page, endpoint, { ...resolved, status: 'PROCESSING' })
  await mount(page, component, options)
  await page.getByRole('button', { name: 'Créer ce dossier' }).click()
  await expect(recordedAnswerStatus(page)).toHaveText('Réponse enregistrée, traitement en cours…')
  await expect(page.getByRole('button').last()).toBeDisabled()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.evaluate(interaction => window.testApp.setProps({ interaction }), resolved)
  await expect(recordedAnswerStatus(page)).toHaveText('Réponse enregistrée.')
})

test('an unrecorded failure allows retrying the same choice', async ({ page }) => {
  let attempts = 0
  await page.route(`${endpoint}/answer`, route => {
    attempts += 1
    return route.fulfill(attempts === 1
      ? { status: 503, json: { detail: 'Unavailable' } }
      : { json: resolved })
  })
  await jsonRoute(page, endpoint, choice)
  await mount(page, component, options)
  const create = page.getByRole('button', { name: 'Créer ce dossier' })
  await create.click()
  await expect(page.getByRole('alert')).toContainText('Réessayez')
  await expect(create).toBeEnabled()
  await create.click()
  await expect(recordedAnswerStatus(page)).toHaveText('Réponse enregistrée.')
  expect(attempts).toBe(2)
})

test('a late response from another room cannot change the current choice', async ({ page }) => {
  let release
  const ready = new Promise(resolve => { release = resolve })
  let submitted = false
  await page.route(`${endpoint}/answer`, async route => {
    submitted = true
    await ready
    await route.fulfill({ json: resolved })
  })
  await mount(page, component, options)
  await page.getByRole('button', { name: 'Créer ce dossier' }).click()
  await expect.poll(() => submitted).toBe(true)
  await page.evaluate(interaction => window.testApp.setProps({ roomId: 'room-2', interaction }), {
    ...choice, id: 'choice-2', title: 'Une autre demande',
  })
  const response = page.waitForResponse(url => url.url().endsWith('/choice-1/answer'))
  release()
  await response
  await expect(page.getByRole('region', { name: 'Une autre demande' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Créer ce dossier' })).toBeEnabled()
  await expect(recordedAnswerStatus(page)).toHaveCount(0)
})
