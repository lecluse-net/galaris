import { test, expect } from '@playwright/test'

async function signIn(page, request) {
  const fixture = await (await request.post('/api/__test/seed')).json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  await page.locator('button[type=submit]').click()
  await expect(page.locator('.user-menu-wrapper').first()).toBeVisible()
}

async function openLab(page, slug) {
  // Use the app navigation: a full document teardown aborts unrelated dashboard
  // requests and WebKit reports those aborts as page errors in the next scenario.
  await page.getByRole('link', { name: 'Laboratoire', exact: true }).click()
  await page.locator(`.lab-home a[href="/lab/${slug}"]`).click()
  await expect(page).toHaveURL(new RegExp(`/lab/${slug}$`))
}

test('every lab exposes its single variable and result', async ({ page, request }) => {
  await signIn(page, request)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  for (const slug of ['dispatcher', 'briefing', 'planner', 'topic-detection', 'memory-extraction', 'learning', 'goal-tracking', 'task-executor', 'conversation-executor', 'voice-executor']) {
    await openLab(page, slug)
    await expect(page.locator('.contract-summary')).toContainText('Variable testée')
    await expect(page.locator('.contract-summary')).toContainText('Résultat à tester')
  }
  await openLab(page, 'ai-evaluations')
  await page.getByText('Tester et juger les diagnostics', { exact: true }).click()
  await expect(page.locator('.contract-summary')).toContainText('Dossier d’exécution')
  expect(errors).toEqual([])
})

test('shared settings belong to the dataset and history belongs to each item on desktop and mobile', async ({ page, request }) => {
  await signIn(page, request)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await openLab(page, 'briefing')
  await page.getByRole('button', { name: 'Nouveau jeu', exact: true }).click()
  let dialog = page.getByRole('dialog').last()
  await dialog.getByLabel('Nom', { exact: true }).fill(`Briefing browser ${Date.now()}`)
  await dialog.getByRole('button', { name: 'Créer', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await page.getByRole('tab', { name: 'Paramètres du jeu', exact: true }).click()
  await expect(page.locator('[data-parameter="history"]')).toHaveCount(0)
  const agentParameter = page.locator('[data-parameter="agent"]')
  await agentParameter.locator('.q-item').first().click()
  await agentParameter.locator('textarea').fill('{"name":"Test agent"}')
  const savedDataset = page.waitForResponse(response => response.request().method() === 'PATCH' && /\/datasets\//.test(response.url()))
  await page.getByRole('button', { name: 'Enregistrer', exact: true }).click()
  await savedDataset
  await page.getByRole('tab', { name: 'Items', exact: true }).click()
  await page.getByRole('button', { name: 'Nouvel item', exact: true }).click()
  dialog = page.getByRole('dialog').last()
  await dialog.getByLabel('Nom', { exact: true }).fill('Prepare the report')
  await dialog.getByRole('button', { name: 'Créer', exact: true }).click()
  dialog = page.getByRole('dialog').last()
  await dialog.getByLabel('Variable : Objectif', { exact: true }).fill('Prepare a verified report')
  await expect(dialog.locator('[data-parameter="agent"]')).toHaveCount(0)
  const history = [{ text: 'Previous request', role: 'human' }]
  await dialog.locator('[data-parameter="history"] .q-item').first().click()
  await dialog.locator('[data-parameter="history"] textarea').fill(JSON.stringify(history))
  const previewResponse = page.waitForResponse(response => response.url().endsWith('/preview'))
  await dialog.getByRole('button', { name: 'Prévisualiser les entrées', exact: true }).click()
  const preview = await (await previewResponse).json()
  expect(preview.input.variable_value).toBe('Prepare a verified report')
  expect(preview.parameters.agent).toEqual({ name: 'Test agent' })
  expect(preview.origins.agent).toBe('dataset')
  expect(Object.keys(preview.input)).toEqual(['variable_value', 'context'])
  expect(preview.input.context.history).toEqual(history)
  expect(preview.native_input.history).toEqual(history)
  expect(preview.origins.history).toBe('item')
  expect(preview.origins.language).toBe('dataset')
  await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  // The responsive table changes after Quasar's screen update. Target the mobile
  // control, not the desktop button that can disappear between pointer events.
  await page.locator('.q-table__grid-content').getByRole('button', { name: 'Visualiser', exact: true }).click()
  await expect(page.getByRole('dialog').getByLabel('Variable : Objectif', { exact: true })).toHaveValue('Prepare a verified report')
  await page.getByRole('dialog').locator('[data-parameter="history"] .q-item').first().click()
  await expect(page.getByRole('dialog').locator('[data-parameter="history"] textarea')).toHaveValue(/Previous request/)
  await page.keyboard.press('Escape')
  expect(errors).toEqual([])
})


test('capture differences require explicit confirmation and cancellation adds nothing', async ({ page, request }, testInfo) => {
  await signIn(page, request)
  await openLab(page, 'briefing')
  await page.getByRole('button', { name: 'Nouveau jeu', exact: true }).click()
  let dialog = page.getByRole('dialog').last()
  await dialog.getByLabel('Nom', { exact: true }).fill(`Shared parameters ${testInfo.testId} ${testInfo.repeatEachIndex}`)
  const created = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/briefing/datasets'))
  await dialog.getByRole('button', { name: 'Créer', exact: true }).click()
  const response = await created
  expect(response.ok(), await response.text()).toBeTruthy()
  await expect(dialog).not.toBeVisible()
  await page.getByRole('tab', { name: 'Items', exact: true }).click()
  const captures = []
  const token = 'a'.repeat(64)
  await page.route('**/evaluation/briefing/datasets/*/cases/from-task', async route => {
    const body = route.request().postDataJSON()
    captures.push(body)
    if (body.confirmation_token !== token) {
      await route.fulfill({ status: 409, json: { detail: {
        code: 'dataset_parameters_mismatch', dataset_name: 'Shared parameters',
        differences: [{ name: 'language', source_value: 'fr', dataset_value: 'en' }],
        confirmation_token: token,
      } } })
    } else {
      await route.fulfill({ status: 201, json: {
        id: 'captured-item', revision: 1, name: 'Captured report', enabled: true,
        readiness: 'draft', input_data: { variable_value: 'Prepare a report' },
        expected_output: { result: 'Report', choices: [] }, source_capture: {},
      } })
    }
  })
  await page.getByRole('button', { name: 'Capturer une source', exact: true }).click()
  dialog = page.getByRole('dialog').last()
  await dialog.getByLabel('URI de la Task source', { exact: true }).fill('00000000-0000-0000-0000-000000000001')
  await dialog.getByRole('button', { name: 'Capturer la Task', exact: true }).click()
  let confirmation = page.getByRole('dialog').filter({ hasText: 'Les paramètres de la source diffèrent' })
  await expect(confirmation).toContainText('Shared parameters')
  await expect(confirmation).toContainText('Dans la source')
  await expect(confirmation).toContainText('Dans le jeu de tests')
  expect(captures).toHaveLength(1)
  await confirmation.getByRole('button', { name: 'Annuler', exact: true }).click()
  await expect(confirmation).not.toBeVisible()
  expect(captures).toHaveLength(1)
  await dialog.getByRole('button', { name: 'Capturer la Task', exact: true }).click()
  confirmation = page.getByRole('dialog').filter({ hasText: 'Les paramètres de la source diffèrent' })
  await confirmation.getByRole('button', { name: 'Ajouter avec les paramètres du jeu', exact: true }).click()
  await expect(page.getByRole('dialog').getByLabel('Variable : Objectif', { exact: true })).toHaveValue('Prepare a report')
  expect(captures).toHaveLength(3)
  expect(captures[2].confirmation_token).toBe(token)
  await expect(page.getByRole('dialog').locator('[data-parameter="language"]')).toHaveCount(0)
  await expect(page.getByRole('dialog').locator('[data-parameter="history"]')).toHaveCount(1)
})
