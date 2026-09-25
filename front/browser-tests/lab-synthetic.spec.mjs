import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const oldDataset = { id: 'existing', name: 'Existing experiment', description: '', revision: 1, parameters: {}, configuration: {}, purpose: 'work' }
const generated = { ...oldDataset, id: 'synthetic', name: 'Observatory', case_count: 3, ready_case_count: 0 }

async function workbench(page, props = {}) {
  await jsonRoute(page, '**/api/evaluation/mechanisms', ['briefing', 'planner'].map(key => ({
    key, executor: null, configuration_schema: {}, algorithm: {},
    contract: { variable_name: 'objective', variable_schema: { type: 'string' }, parameters_schema: {}, parameter_defaults: {}, result_name: 'briefing_and_resources' },
  })))
  await jsonRoute(page, '**/api/evaluation/config', { lab_llm_id: 7, llms: [{ id: 7, label: 'Generator' }] })
  for (const key of ['briefing', 'planner']) {
    await jsonRoute(page, `**/api/evaluation/${key}/datasets`, [oldDataset])
    await jsonRoute(page, `**/api/evaluation/${key}/datasets/*/cases`, [])
    await jsonRoute(page, `**/api/evaluation/${key}/datasets/*/runs?*`, [])
  }
  await mount(page, 'app/lab/components/LabWorkbench.vue', { props: { mechanism: 'briefing', canEdit: true, ...props } })
}

async function openGenerator(page) {
  await page.getByRole('button', { name: 'Generate a synthetic dataset', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name', { exact: true }).fill('Observatory')
  await dialog.getByLabel('Number of cases (1–20)', { exact: true }).fill('3')
  await dialog.getByLabel('Domain, scenarios and constraints to test', { exact: true }).fill('Summarize fictional observatory schedules.')
  return dialog
}

test('synthetic generation sends customization, preserves failed drafts and opens the new experiment', async ({ page }) => {
  const requests = []
  await page.route('**/api/evaluation/briefing/datasets/synthetic', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill(requests.length === 1
      ? { status: 422, json: { detail: 'Generator unavailable' } }
      : { status: 201, json: { dataset: generated, cost: 0.012 } })
  })
  await workbench(page)
  const dialog = await openGenerator(page)
  await page.screenshot({ path: '/artifacts/lab-synthetic-desktop.png', animations: 'disabled' })
  await dialog.getByRole('button', { name: 'Generate', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Generator unavailable')
  await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('Observatory')
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
  await expect(dialog).not.toBeVisible()
  await page.getByRole('button', { name: 'Generate a synthetic dataset', exact: true }).click()
  await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('Observatory')
  await dialog.getByRole('button', { name: 'Generate', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  expect(requests).toEqual(Array(2).fill({ name: 'Observatory', instructions: 'Summarize fictional observatory schedules.', count: 3, language: 'en', llm_id: 7, categories: ['nominal', 'ambiguity', 'incomplete'], source_dataset_id: 'existing', source_revision: 1 }))
  await expect(page.getByText('Observatory', { exact: true })).toBeVisible()
  await expect(page.getByText(/3 drafts to review/)).toBeVisible()
  await page.getByLabel('Dataset', { exact: true }).click()
  await expect(page.getByRole('option', { name: /Existing experiment/ })).toBeVisible()
})

test('closing and reopening a pending generation cannot submit it twice or erase active edits', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  let calls = 0
  await page.route('**/api/evaluation/briefing/datasets/synthetic', async route => {
    calls++; await pending
    await route.fulfill({ status: 201, json: { dataset: generated, cost: 0.012 } })
  })
  await workbench(page)
  let dialog = await openGenerator(page)
  await dialog.getByRole('button', { name: 'Generate', exact: true }).click()
  await expect(dialog.getByRole('status')).toContainText('Generating')
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
  await page.getByRole('button', { name: 'Generate a synthetic dataset', exact: true }).click()
  dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Name', { exact: true })).toBeDisabled()
  await expect(dialog.getByRole('status')).toContainText('Generating')
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } })
  await expect(dialog).toHaveCount(0)
  await page.getByRole('tab', { name: 'Dataset settings', exact: true }).click()
  await page.getByLabel('Name', { exact: true }).fill('Unsaved experiment name')
  release()
  await expect(page.getByText(/3 drafts to review/)).toBeVisible()
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Unsaved experiment name')
  expect(calls).toBe(1)
})

test('late generation from another lab cannot change the current experiment', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/evaluation/briefing/datasets/synthetic', async route => {
    await pending
    await route.fulfill({ status: 201, json: { dataset: generated, cost: 0.012 } })
  })
  await workbench(page)
  const dialog = await openGenerator(page)
  await dialog.getByRole('button', { name: 'Generate', exact: true }).click()
  await expect(dialog.getByRole('status')).toBeVisible()
  await page.evaluate(() => window.testApp.setProps({ mechanism: 'planner' }))
  await expect(dialog).not.toBeVisible()
  release()
  await page.getByRole('button', { name: 'Generate a synthetic dataset', exact: true }).click()
  await expect(page.getByRole('dialog').getByLabel('Name', { exact: true })).toHaveValue('')
  await expect(page.getByText(/3 drafts to review/)).toHaveCount(0)
})

test('read-only labs do not offer generation', async ({ page }) => {
  await workbench(page, { canEdit: false })
  await expect(page.getByLabel('Dataset', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Generate a synthetic dataset', exact: true })).toHaveCount(0)
})

test('mobile generation requires a configured model and valid case coverage', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await mount(page, 'app/lab/components/LabSyntheticDatasetDialog.vue', { props: { modelValue: true, mechanism: 'voice_executor', models: [], defaultModel: null } })
  const dialog = page.getByRole('dialog')
  const generate = dialog.getByRole('button', { name: 'Generate', exact: true })
  await dialog.getByLabel('Name', { exact: true }).fill('Spoken schedules')
  await expect(generate).toBeDisabled()
  await page.evaluate(() => window.testApp.setProps({ models: [{ id: 7, label: 'Generator' }] }))
  await dialog.getByLabel('Generator model', { exact: true }).click()
  await page.getByRole('option', { name: 'Generator', exact: true }).click()
  await expect(page.getByRole('option', { name: 'Generator', exact: true })).toHaveCount(0)
  await dialog.getByLabel('Number of cases (1–20)', { exact: true }).fill('1')
  await expect(generate).toBeDisabled()
  await dialog.getByLabel('Number of cases (1–20)', { exact: true }).fill('3')
  await expect(generate).toBeEnabled()
  await page.screenshot({ path: '/artifacts/lab-synthetic-mobile.png', fullPage: true, animations: 'disabled' })
  await dialog.getByRole('button', { name: 'Close', exact: true }).last().click()
  await expect(dialog).not.toBeVisible()
})

test('contextual generation requires saved settings and can explicitly start a fresh environment', async ({ page }) => {
  const requests = []
  await page.route('**/api/evaluation/briefing/datasets/synthetic', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ status: 201, json: { dataset: generated, cost: 0.012 } })
  })
  await workbench(page)
  await page.getByRole('tab', { name: 'Dataset settings', exact: true }).click()
  await page.getByLabel('Name', { exact: true }).fill('Unsaved context')
  const dialog = await openGenerator(page)
  const generate = dialog.getByRole('button', { name: 'Generate', exact: true })
  await expect(dialog.getByText('Save your dataset changes before generating cases in this context.')).toBeVisible()
  await expect(generate).toBeDisabled()
  await dialog.getByRole('switch', { name: /Use the context of dataset/ }).click()
  await expect(generate).toBeEnabled()
  await generate.click()
  await expect(dialog).not.toBeVisible()
  expect(requests).toHaveLength(1)
  expect(requests[0]).not.toHaveProperty('source_dataset_id')
  expect(requests[0]).not.toHaveProperty('source_revision')
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Unsaved context')
})
