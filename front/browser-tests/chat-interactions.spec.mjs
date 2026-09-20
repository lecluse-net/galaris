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
  await expect(page.getByRole('status')).toHaveText('Réponse enregistrée.')
  await expect(create).toHaveAttribute('aria-pressed', 'true')
})

test('a click submits one exact choice, locks both buttons and survives reopening', async ({ page }) => {
  let release
  const ready = new Promise(resolve => { release = resolve })
  const submissions = []
  await page.route(`${endpoint}/answer`, async route => {
    submissions.push(route.request().postDataJSON())
    await ready
    await route.fulfill({ json: resolved })
  })
  await mount(page, component, options)
  const create = page.getByRole('button', { name: 'Créer ce dossier' })
  const reject = page.getByRole('button', { name: 'Laisser cette activité sans classement' })
  await create.click()
  await expect.poll(() => submissions).toEqual([{ option_id: 'create' }])
  await expect(create).toBeDisabled()
  await expect(reject).toBeDisabled()
  release()
  await expect(page.getByRole('status')).toHaveText('Réponse enregistrée.')
  await expect(create).toHaveAttribute('aria-pressed', 'true')
  // A history request started before the click may return the old pending snapshot.
  await page.evaluate(interaction => window.testApp.setProps({ interaction }), choice)
  await expect(create).toBeDisabled()
  await mount(page, component, { ...options, props: { ...options.props, interaction: resolved } })
  await expect(page.getByRole('status')).toHaveText('Réponse enregistrée.')
  await expect(create).toBeDisabled()
  expect(submissions).toHaveLength(1)
})

test('expired and read-only choices cannot be submitted', async ({ page }) => {
  await mount(page, component, { ...options, props: { ...options.props, readonly: true } })
  await expect(page.getByRole('button').first()).toBeDisabled()
  await page.evaluate(interaction => window.testApp.setProps({ readonly: false, interaction }), {
    ...choice, expires_at: '2000-01-01T00:00:00Z',
  })
  await expect(page.getByRole('status')).toHaveText('Cette demande a expiré.')
  await expect(page.getByRole('button').first()).toBeDisabled()
})

test('a lost response reloads the recorded decision before enabling another answer', async ({ page }) => {
  await page.route(`${endpoint}/answer`, route => route.fulfill({ status: 503, json: { detail: 'Lost response' } }))
  await jsonRoute(page, endpoint, { ...resolved, status: 'PROCESSING' })
  await mount(page, component, options)
  await page.getByRole('button', { name: 'Créer ce dossier' }).click()
  await expect(page.getByRole('status')).toHaveText('Réponse enregistrée, traitement en cours…')
  await expect(page.getByRole('button').last()).toBeDisabled()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.evaluate(interaction => window.testApp.setProps({ interaction }), resolved)
  await expect(page.getByRole('status')).toHaveText('Réponse enregistrée.')
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
  await expect(page.getByRole('status')).toHaveText('Réponse enregistrée.')
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
  await expect(page.getByRole('status')).toHaveCount(0)
})
