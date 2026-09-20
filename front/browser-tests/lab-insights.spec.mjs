import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const rubric = { version: 'test:1', dimensions: [{ code: 'grounding', label: 'Grounding', criteria: 'Claims must have evidence.', weight_percent: 100 }] }
const result = (id, overrides = {}) => ({
  id, repetition: 1, case_snapshot: { id: 'case', name: id, input_data: { variable_value: 'Report' }, expected_output: { result: 'Reference' } },
  actual_output: { result: 'Readable candidate answer' }, error: null, verdict: 'pass', score_percent: 90,
  score_details: { checks: [{ code: 'schema', passed: true, critical: true, detail: 'Output respects the contract' }] },
  judge_output: { explanation: 'Supported by evidence', dimensions: [{ code: 'grounding', score_percent: 90, assessment: 'Sources are present' }] },
  ...overrides,
})

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
test.describe('Lab at ' + viewport.width, () => {
  test.use({ viewport })

test('results expose evidence, filter failures and distinguish missing judgments in stability', async ({ page }) => {
  const run = { repetitions: 3, configuration_snapshot: { rubric }, results: [
    result('Successful'),
    result('Critical', { repetition: 2, verdict: 'fail', score_percent: 40, judge_output: { explanation: 'Unsupported claims', critical_failures: ['Invented evidence'] } }),
    result('Unjudged', { repetition: 3, score_percent: null, verdict: 'inconclusive', judge_output: { error: 'Judge unavailable' } }),
  ] }
  await mount(page, 'app/lab/components/LabResultsPanel.vue', { props: { run } })
  await expect(page.getByText('1/3 passes · 3 executions · 2 judgments · 1 failures')).toBeVisible()
  await expect(page.getByText('Mean 65.0 · minimum 40.0 · maximum 90.0 · standard deviation 25.0')).toBeVisible()
  await page.getByText('Successful', { exact: true }).last().click()
  await expect(page.getByText('Readable candidate answer', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('Sources are present', { exact: true })).toBeVisible()
  await page.getByLabel('Filter results', { exact: true }).click()
  await page.getByRole('option', { name: 'Critical failures', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('1/3 results displayed')
  await expect(page.getByText('Unjudged', { exact: true })).not.toBeVisible()
  await page.getByText('Critical', { exact: true }).click()
  await expect(page.getByText('Invented evidence', { exact: true })).toBeVisible()
  await page.getByLabel('Filter results', { exact: true }).click()
  await page.getByRole('option', { name: 'Unjudged', exact: true }).click()
  await page.locator('.q-expansion-item__container > .q-item').filter({ hasText: /^Unjudged/ }).click()
  await expect(page.getByText('Judge unavailable', { exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('lab-results.png'), fullPage: true, animations: 'disabled' })
})

test('human review saves independent notes before disclosing the judge and preserves them on reopening', async ({ page }) => {
  const item = { result_id: 'result', name: 'Report', repetition: 1, input: { variable_value: 'Report' }, reference: 'Example only', output: 'Candidate answer', assessment: null, human_score: null, human_verdict: null, judge: null }
  const queue = { campaign_id: 'campaign', rubric, parameters: { language: 'en' }, items: [item] }
  let submitted
  await page.route('**/api/evaluation/briefing/runs/run/human-review', async route => {
    if (route.request().method() === 'POST') {
      submitted = route.request().postDataJSON()
      Object.assign(item, { assessment: submitted, human_score: 50, human_verdict: 'fail', judge: { score_percent: 90, verdict: 'pass', output: { explanation: 'Automatic approval', dimensions: [{ code: 'grounding', score_percent: 90, assessment: 'Automatic grounds' }] } } })
    }
    await route.fulfill({ json: queue })
  })
  await mount(page, 'app/lab/components/LabHumanReviewDialog.vue', { props: { mechanism: 'briefing', runId: 'run', modelValue: true, canEdit: true } })
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Candidate answer', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Automatic approval')).not.toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Save and reveal judgment' })).toBeDisabled()
  await dialog.getByLabel('Your score — Grounding', { exact: true }).fill('50')
  await dialog.getByLabel('Your assessment — Grounding', { exact: true }).fill('Missing sources')
  await dialog.getByLabel('Overall assessment', { exact: true }).fill('Insufficient support')
  await dialog.getByRole('button', { name: 'Save and reveal judgment' }).click()
  await expect(dialog.getByText('Automatic approval', { exact: true })).toBeVisible()
  expect(submitted).toMatchObject({ campaign_id: 'campaign', result_id: 'result', dimensions: [{ code: 'grounding', score_percent: 50, assessment: 'Missing sources' }] })
  await expect(dialog.getByText('You: 50 · Judge: 90 · Judge − human: 40.0')).toBeVisible()
  await expect(dialog.getByText('1 comparisons · 1 verdict disagreements · mean absolute difference 40.0')).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Save and reveal judgment' })).not.toBeVisible()
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await page.evaluate(() => window.testApp.setProps({ modelValue: true }))
  await expect(dialog.getByText('Missing sources', { exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('lab-review.png'), fullPage: true, animations: 'disabled' })
})

test('workbench saves dataset roles and item categories and submits bounded repeated runs', async ({ page }) => {
  const dataset = { id: 'dataset', name: 'Regression', revision: 1, description: '', purpose: 'work', parameters: {}, configuration: {}, prompt_suffix: null }
  const item = { id: 'case', name: 'Incident', revision: 1, enabled: true, readiness: 'ready', categories: [], input_data: { variable_value: 'Report' }, expected_output: 'Reference', source_capture: {} }
  await jsonRoute(page, '**/api/evaluation/mechanisms', [{ key: 'briefing', configuration_schema: {}, algorithm: {}, contract: { variable_name: 'objective', variable_schema: { type: 'string' }, parameters_schema: {}, parameter_defaults: {}, result_name: 'briefing_and_resources' } }])
  await jsonRoute(page, '**/api/evaluation/config', { lab_llm_id: 1, llms: [{ id: 1, label: 'Model' }] })
  await jsonRoute(page, '**/api/evaluation/briefing/datasets', [dataset])
  await jsonRoute(page, '**/api/evaluation/briefing/datasets/dataset/cases', [item])
  await jsonRoute(page, '**/api/evaluation/briefing/datasets/dataset/runs?*', [])
  let savedDataset, savedItem, started
  await page.route('**/api/evaluation/briefing/datasets/dataset', async route => { savedDataset = route.request().postDataJSON(); await route.fulfill({ json: { ...dataset, ...savedDataset, revision: 2 } }) })
  await page.route('**/api/evaluation/briefing/cases/case', async route => { savedItem = route.request().postDataJSON(); await route.fulfill({ json: { ...item, ...savedItem, revision: 2 } }) })
  const run = { id: 'run', status: 'completed', repetitions: 3, total_cases: 3, completed_cases: 3, judged_cases: 3, candidate_cost: 0.3, judge_cost: 0.06, llm_snapshot: {}, judge_llm_snapshot: {}, configuration_snapshot: {}, results: [], campaigns: [] }
  await page.route('**/api/evaluation/briefing/datasets/dataset/runs', async route => { started = route.request().postDataJSON(); await route.fulfill({ json: run }) })
  await jsonRoute(page, '**/api/evaluation/briefing/runs/run', run)
  await mount(page, 'app/lab/components/LabWorkbench.vue', { props: { mechanism: 'briefing', canEdit: true } })
  await page.getByRole('tab', { name: 'Dataset settings', exact: true }).click()
  await page.getByLabel('Dataset role', { exact: true }).click()
  await page.getByRole('option', { name: 'Validation', exact: true }).click()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => savedDataset?.purpose).toBe('validation')
  await page.getByRole('tab', { name: 'Items', exact: true }).click()
  await page.getByRole('button', { name: 'View', exact: true }).click()
  await page.getByLabel('Coverage categories', { exact: true }).click()
  await page.getByRole('option', { name: 'Real incident', exact: true }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => savedItem?.categories).toEqual(['incident'])
  await page.getByRole('tab', { name: 'Benchmarks', exact: true }).click()
  await page.getByLabel('Repetitions per item (1 to 20)', { exact: true }).fill('3')
  await page.getByLabel('Candidate + judge budget (USD, optional)', { exact: true }).fill('0')
  await expect(page.getByRole('button', { name: 'Run both passes', exact: true })).toBeDisabled()
  await page.getByLabel('Candidate + judge budget (USD, optional)', { exact: true }).fill('')
  await expect(page.getByRole('button', { name: 'Run both passes', exact: true })).toBeEnabled()
  await page.getByLabel('Candidate + judge budget (USD, optional)', { exact: true }).fill('0.5')
  await page.getByRole('button', { name: 'Run both passes', exact: true }).click()
  await expect.poll(() => started).toEqual({ llm_id: 1, judge_llm_id: 1, repetitions: 3, max_cost: 0.5 })
})

})
}
