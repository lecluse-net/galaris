import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const datasets = [{ id: 'baseline', name: 'Baseline corpus', parameters: {}, configuration: {} }, { id: 'variant', name: 'Variant corpus', parameters: {}, configuration: {} }]
const run = (id, label) => ({ id, created_at: '2026-01-01T12:00:00Z', status: 'completed', total_cases: 3, completed_cases: 3, judged_cases: 3, llm_snapshot: { label }, configuration_snapshot: {} })
const before = run('before-run', 'Candidate before'), after = run('after-run', 'Candidate after')
const item = (name, changes = {}) => ({ name, left_result_id: name, right_result_id: 'after-' + name, pairing: 'matched', repetition: 1, score_delta: -20, cost_delta: -0.01, duration_delta: 1, left_score: 20, right_score: 0, left_cost: 0.02, right_cost: 0.01, left_duration: 1, right_duration: 2, left_verdict: 'pass', right_verdict: 'fail', input: 'Synthetic input', reference: 'Reference only', left_output: 'Original answer', right_output: 'Changed answer', left_judgment: { explanation: 'Original evidence' }, right_judgment: { explanation: 'New evidence', critical_failures: ['Unsupported claim'] }, left_checks: {}, right_checks: {}, left_error: null, right_error: null, ...changes })
const summary = { cases: 4, observations: 6, matched: 5, missing_left: 0, missing_right: 1, ambiguous: 0, unjudged: 1, failed: 0, increased: 2, decreased: 1, equal: 1 }
const comparison = { axis: 'model', comparable: true, summary, differences: ['candidate'], blockers: [], left: before, right: after, items: [item('A result')], next_offset: null }
const risks = { assessed_pairs: 12, introduced_critical: 1, pass_to_fail: 1, dimensions: [{ code: 'grounding', pairs: 12, decreased: 1, increased: 0, equal: 11, mean_delta: -5 }] }
const metric = { pairs: 12, left_median: 2, right_median: 1, median_delta: -1 }
const performance = { first_output: metric, duration: metric, cost: { ...metric, left_median: 0.02, right_median: 0.01, median_delta: -0.01 }, quality: { ...metric, left_median: 70, right_median: 75, median_delta: 5 } }

async function routes(page, mechanism = 'briefing') {
  await jsonRoute(page, `**/api/evaluation/${mechanism}/datasets/baseline/runs?*`, [before, after])
  await jsonRoute(page, `**/api/evaluation/${mechanism}/datasets/variant/runs?*`, [after])
}
async function choose(page) {
  const selectors = page.getByRole('dialog').getByLabel('Evaluation', { exact: true })
  await selectors.nth(0).click()
  await page.getByRole('option', { name: /Candidate before/ }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await selectors.nth(1).click()
  await page.getByRole('option', { name: /Candidate after/ }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
}
for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test.describe('Lab comparison at ' + viewport.width, () => {
    test.use({ viewport })
    test('global risk filters reveal off-page regressions despite a higher overall score', async ({ page }) => {
      await routes(page)
      const requests = []
      await page.route('**/api/evaluation/briefing/runs/compare?*', route => {
        const params = Object.fromEntries(new URL(route.request().url()).searchParams)
        requests.push(params)
        return route.fulfill({ json: { ...comparison, risks, performance, items: params.focus === 'all'
          ? [item('Ordinary case')]
          : [item('Previously off-page case', { introduced_critical: true, pass_to_fail: true, dimension_deltas: { grounding: -60 }, score_delta: 5, left_first_output_seconds: 2, right_first_output_seconds: 1 })] } })
      })
      await mount(page, 'app/lab/components/LabComparisonDialog.vue', { props: { mechanism: 'briefing', datasets, initialDatasetId: 'baseline', modelValue: true } })
      await choose(page)
      await page.getByRole('button', { name: 'Compare', exact: true }).click()
      await expect(page.getByRole('heading', { name: /Ordinary case/ })).toBeVisible()
      for (const [focus, label] of [['critical', '1 newly critical outcomes — view cases'], ['verdict', '1 pass-to-fail changes — view cases'], ['dimension', 'View decreases: grounding']]) {
        await page.getByRole('button', { name: label, exact: true }).click()
        await expect(page.getByRole('heading', { name: /Previously off-page case/ })).toBeVisible()
        await expect(page.getByText('A critical failure appeared.', { exact: true })).toBeVisible()
        await expect(page.getByText('Verdict changed from pass to fail.', { exact: true })).toBeVisible()
        await expect(page.getByText('grounding: -60.0 points.', { exact: true })).toBeVisible()
        await expect(page.getByText('First observed output: 1.00 s.', { exact: true })).toBeVisible()
        expect(requests.at(-1)).toMatchObject({ focus, offset: '0' })
        if (focus === 'dimension') expect(requests.at(-1).dimension).toBe('grounding')
        await expect(page.getByText('12 pairs · before 2 · after 1 · median paired difference -1').first()).toBeVisible()
        await page.getByRole('button', { name: 'All cases', exact: true }).click()
        await expect(page.getByRole('heading', { name: /Ordinary case/ })).toBeVisible()
      }
      await page.getByRole('button', { name: '1 newly critical outcomes — view cases', exact: true }).click()
      await expect(page.getByRole('heading', { name: /Previously off-page case/ })).toBeVisible()
      await page.getByRole('button', { name: 'Swap before and after' }).click()
      await page.getByRole('button', { name: 'Compare', exact: true }).click()
      await expect(page.getByRole('heading', { name: /Ordinary case/ })).toBeVisible()
      expect(requests.at(-1)).toMatchObject({ focus: 'all', left_run_id: after.id })
    })
    test('read-only comparison shows zero scores, evidence, missing results, pagination and reversed selections', async ({ page }) => {
      await routes(page)
      const requests = []
      await page.route('**/api/evaluation/briefing/runs/compare?*', route => {
        const params = Object.fromEntries(new URL(route.request().url()).searchParams)
        requests.push(params)
        return route.fulfill({ json: Number(params.offset) > 0 ? { ...comparison, items: [item('Next case')], next_offset: null } : {
          ...comparison, next_offset: 50, items: [item('A result'), item('Missing result', { pairing: 'missing', score_delta: null, right_score: null, right_output: null }), item('Unjudged result', { score_delta: null, right_score: null, right_judgment: null, right_verdict: null })],
        } })
      })
      await mount(page, 'app/lab/components/LabComparisonDialog.vue', { props: { mechanism: 'briefing', datasets, initialDatasetId: 'baseline', modelValue: true } })
      const dialog = page.getByRole('dialog')
      await expect(dialog.getByRole('button', { name: 'Compare', exact: true })).toBeDisabled()
      await choose(page)
      await dialog.getByLabel('Dataset', { exact: true }).nth(1).click()
      await page.getByRole('option', { name: 'Variant corpus', exact: true }).click()
      await expect(dialog.getByRole('button', { name: 'Compare', exact: true })).toBeDisabled()
      await dialog.getByLabel('Evaluation', { exact: true }).nth(1).click()
      await page.getByRole('option', { name: /Candidate after/ }).click()
      await dialog.getByRole('button', { name: 'Compare', exact: true }).click()
      await expect(dialog.getByText('Original answer', { exact: true }).first()).toBeVisible()
      await expect(dialog.getByText('Changed answer', { exact: true }).first()).toBeVisible()
      await expect(dialog.getByText('Unsupported claim', { exact: true }).first()).toBeVisible()
      await expect(dialog.getByText(/Score 0.0 %/).first()).toBeVisible()
      await expect(dialog.getByText('Displayed page: 0 scores increased · 1 decreased · 0 unchanged · 2 without comparable scores.')).toBeVisible()
      const globalCoverage = dialog.getByText('Global summary: 4 distinct cases · 6 observations including repetitions · 5 paired.')
      await expect(globalCoverage).toBeVisible()
      await expect(dialog.getByText(/2 scores increased · 1 decreased · 1 unchanged/)).toBeVisible()
      await expect(dialog.getByText('No matching result after.').first()).toBeVisible()
      await expect(dialog.getByText('Unjudged', { exact: true })).toBeVisible()
      await page.screenshot({ path: test.info().outputPath('comparison.png'), fullPage: true })
      await dialog.getByText('Changed answer', { exact: true }).first().scrollIntoViewIfNeeded()
      await page.screenshot({ path: test.info().outputPath('comparison-answers.png'), fullPage: true })
      await dialog.getByText('Unjudged', { exact: true }).scrollIntoViewIfNeeded()
      await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeInViewport()
      await dialog.getByRole('button', { name: 'Next', exact: true }).click()
      await expect(dialog.getByRole('heading', { name: /Next case/ })).toBeVisible()
      await expect(globalCoverage).toBeVisible()
      expect(requests.at(-1)).toMatchObject({ offset: '50', limit: '50', left_run_id: before.id, right_run_id: after.id })
      await dialog.getByRole('button', { name: 'Swap before and after' }).click()
      await expect(dialog.getByText('Changed answer', { exact: true })).not.toBeVisible()
      await dialog.getByRole('button', { name: 'Compare', exact: true }).click()
      await expect.poll(() => requests.at(-1)?.left_run_id).toBe(after.id)
      expect(requests.at(-1).right_run_id).toBe(before.id)
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(dialog).not.toBeVisible()
      await page.evaluate(() => window.testApp.setProps({ modelValue: true }))
      await expect(dialog.getByRole('button', { name: 'Compare', exact: true })).toBeDisabled()
      await expect(dialog.getByText('Changed answer', { exact: true })).not.toBeVisible()
    })
  })
}

test('errors can be retried and late comparisons cannot cross selections or Lab context', async ({ page }) => {
  await routes(page)
  await routes(page, 'planner')
  let resolveLate, requested = false, failed = true
  await page.route('**/api/evaluation/briefing/runs/compare?*', async route => {
    if (failed) { failed = false; return route.fulfill({ status: 503, json: { detail: 'Synthetic unavailable' } }) }
    requested = true
    await new Promise(resolve => { resolveLate = resolve })
    await route.fulfill({ json: comparison }).catch(() => {})
  })
  await jsonRoute(page, '**/api/evaluation/planner/runs/compare?*', { ...comparison, comparable: false, blockers: ['corpus', 'judge', 'ambiguous_case_pairing'], items: [item('Ambiguous', { pairing: 'ambiguous', score_delta: null })] })
  await mount(page, 'app/lab/components/LabComparisonDialog.vue', { props: { mechanism: 'briefing', datasets, initialDatasetId: 'baseline', modelValue: true } })
  await choose(page)
  await page.getByRole('button', { name: 'Compare', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Synthetic unavailable')
  await page.getByRole('button', { name: 'Compare', exact: true }).click()
  await expect.poll(() => requested).toBe(true)
  await page.getByLabel('Change being studied', { exact: true }).click()
  await page.getByRole('option', { name: 'Prompt', exact: true }).click()
  resolveLate()
  await expect(page.getByText('Original answer', { exact: true })).not.toBeVisible()
  await page.evaluate(() => window.testApp.setProps({ mechanism: 'planner' }))
  await choose(page)
  await page.getByRole('button', { name: 'Compare', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Different corpora')
  await expect(page.getByRole('status')).toContainText('Different judges')
  await expect(page.getByText('No progress summary is calculated for these configurations.')).toBeVisible()
  await expect(page.getByText(/2 scores increased · 1 decreased · 1 unchanged/)).not.toBeVisible()
  await expect(page.getByText('Ambiguous pairing: no after result was selected.').first()).toBeVisible()
  await expect(page.getByText('Changed answer', { exact: true })).not.toBeVisible()
})

for (const mechanism of ['dispatcher', 'task_analysis', 'briefing', 'planner', 'topic_classification', 'memory_extraction', 'outcome_reflection', 'goal_tracking', 'task_executor', 'conversation_executor', 'voice_executor']) {
  test(`${mechanism}: comparison is reachable without edit permission`, async ({ page }) => {
    await routes(page, mechanism)
    await jsonRoute(page, '**/api/evaluation/config', { llms: [], decision_llms: [] })
    await jsonRoute(page, '**/api/evaluation/mechanisms', [{ key: mechanism, configuration_schema: {}, algorithm: {}, contract: { variable_name: 'objective', variable_schema: {}, parameters_schema: {}, parameter_defaults: {}, result_name: 'result' } }])
    await jsonRoute(page, `**/api/evaluation/${mechanism}/datasets`, datasets)
    await jsonRoute(page, `**/api/evaluation/${mechanism}/datasets/baseline/cases`, [])
    await jsonRoute(page, `**/api/evaluation/${mechanism}/runs/compare?*`, comparison)
    await mount(page, 'app/lab/components/LabWorkbench.vue', { props: { mechanism, canEdit: false } })
    await page.getByRole('tab', { name: 'Benchmarks', exact: true }).click()
    await page.getByRole('button', { name: 'Before / after', exact: true }).click()
    await choose(page)
    await page.getByRole('button', { name: 'Compare', exact: true }).click()
    await expect(page.getByText('Original answer', { exact: true })).toBeVisible()
    await expect(page.getByText('Changed answer', { exact: true })).toBeVisible()
  })
}

test('run-list retry, late dataset response, empty and incomplete evaluations stay explicit', async ({ page }) => {
  let failure = true, release, pending = false
  await page.route('**/api/evaluation/briefing/datasets/baseline/runs?*', route => route.fulfill(failure ? { status: 503, json: { detail: 'Runs unavailable' } } : { json: [before, after] }))
  await page.route('**/api/evaluation/briefing/datasets/variant/runs?*', async route => {
    pending = true
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: [run('obsolete', 'Obsolete selection')] })
  })
  await jsonRoute(page, '**/api/evaluation/briefing/runs/compare?*', { ...comparison, left: { ...before, status: 'partial', judged_cases: 0 }, items: [] })
  await mount(page, 'app/lab/components/LabComparisonDialog.vue', { props: { mechanism: 'briefing', datasets, initialDatasetId: 'baseline', modelValue: true } })
  await expect(page.getByRole('alert')).toHaveCount(2)
  failure = false
  await page.getByRole('button', { name: 'Retry', exact: true }).first().click()
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  const dataset = page.getByRole('dialog').getByLabel('Dataset', { exact: true }).nth(1)
  await dataset.click()
  await page.getByRole('option', { name: 'Variant corpus', exact: true }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect.poll(() => pending).toBe(true)
  await dataset.click()
  await page.getByRole('option', { name: 'Baseline corpus', exact: true }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
  release()
  await choose(page)
  await page.getByRole('button', { name: 'Compare', exact: true }).click()
  await expect(page.getByText(/At least one evaluation is incomplete/)).toBeVisible()
  await expect(page.getByText('No executed cases to compare on this page.')).toBeVisible()
  await page.getByLabel('Cases per page', { exact: true }).click()
  await expect(page.getByRole('option')).toHaveText(['10', '20', '50', '100', '500'])
  await page.getByRole('option', { name: '500', exact: true }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
  // Backdrop dismissal remains available in this read-only workflow.
  await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
  await expect(page.getByRole('dialog')).not.toBeVisible()
})
