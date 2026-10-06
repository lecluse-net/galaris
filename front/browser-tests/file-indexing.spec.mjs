import { test, expect, mount } from './fixtures.mjs'

for (const width of [1440, 390]) {
  test(`Dream opens tracking and separates history and indexing at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const overview = {
      runtime: { status: 'stopped', phase: 'stopped', reason: 'not_started', worker_running: false,
        current_mechanism: null, current_subject_kind: null, current_subject_id: null,
        last_cycle_at: null, last_cycle_finished_at: null, next_cycle_at: null,
        state_changed_at: null, cycle_count: 0, last_error_type: null },
      total_operations: 0, completed_operations: 0, pending_operations: 0, terminal_tasks: 0,
      unscanned_tasks: 0, running_receipts: 0, retry_receipts: 0, successful_receipts: 0,
      error_receipts: 0, memories_created: 0, memories_linked: 0, total_cost: 0, mechanisms: [],
    }
    await page.route('**/api/dream/overview', route => route.fulfill({ json: overview }))
    await page.route('**/api/dream/receipts?*', route => route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } }))
    await page.route('**/api/agents?*', route => route.fulfill({ json: [{ id: 7, first_name: 'Alice', last_name: 'Example', has_avatar: false }] }))
    let indexingReads = 0
    await page.route('**/api/file-share/indexing?*', route => {
      indexingReads++
      expect(new URL(route.request().url()).searchParams.get('agent_id')).toBe('7')
      return route.fulfill({ json: { runs: [], total: 0, pending_repairs: 0, failed_repairs: 0 } })
    })
    await mount(page, 'app/dream/pages/index.vue', { locale: 'fr', route: '/dream?agent=7', privileges: ['MEMORY_ACCESS', 'MEMORY_EDIT'] })
    await expect(page.getByRole('tab', { name: 'Suivi', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('.dream-history-card')).toHaveCount(0)
    expect(indexingReads).toBe(0)
    await page.getByRole('button', { name: /Erreurs/ }).click()
    await expect(page.getByRole('tab', { name: 'Historique', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('.dream-history-card')).toBeVisible()
    const indexingTab = page.getByRole('tab', { name: 'Indexation', exact: true })
    await indexingTab.focus()
    await indexingTab.press('Enter')
    await expect(page.getByText('Aucun parcours pour cet agent.')).toBeVisible()
    await expect(page.locator('.dream-history-card')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('dream-tabs.png'), animations: 'disabled' })
    await page.getByRole('tab', { name: 'Suivi', exact: true }).click()
    await indexingTab.click()
    await expect(page.getByText('Aucun parcours pour cet agent.')).toBeVisible()
  })
}

for (const width of [1440, 390]) {
  test(`file indexing starts, reports progress and cancels at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const writes = [], cancellations = []
    const run = { id: 'synthetic-run', root_uri: 'scan-test://folder/', status: 'running', scanned: 501, directories: 1, error_type: null }
    const runs = []
    await page.route('**/api/file-share/indexing*', route => {
      const request = route.request()
      if (request.method() === 'POST') {
        writes.push(request.postDataJSON())
        runs.push(run)
        return route.fulfill({ json: run })
      }
      return route.fulfill({ json: { runs, total: runs.length, pending_repairs: 2, failed_repairs: 0 } })
    })
    await page.route('**/api/file-share/indexing/synthetic-run/cancel?*', route => {
      cancellations.push(route.request().url())
      run.status = 'cancelled'
      return route.fulfill({ json: { cancelled: true } })
    })
    await mount(page, 'app/dream/components/FileIndexPanel.vue', { props: { agentId: 7, editable: true } })
    await expect(page.getByText('No traversal for this agent.')).toBeVisible()
    await page.getByLabel('Source root (URI)').fill('scan-test://folder/')
    await page.getByRole('button', { name: 'Index now', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0]).toEqual({ agent_id: 7, root_uri: 'scan-test://folder/' })
    await expect(page.getByText('Running', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect.poll(() => cancellations.length).toBe(1)
    await expect(page.getByText('Cancelled', { exact: true })).toBeVisible()
  })
}

test('file indexing read-only viewer can retry a failed load without mutation controls', async ({ page }) => {
  let attempts = 0
  await page.route('**/api/file-share/indexing?*', route => {
    attempts++
    return attempts === 1 ? route.fulfill({ status: 503, json: {} }) : route.fulfill({ json: { runs: [], total: 0, pending_repairs: 0, failed_repairs: 0 } })
  })
  await mount(page, 'app/dream/components/FileIndexPanel.vue', { props: { agentId: 7, editable: false } })
  await expect(page.getByRole('alert')).toContainText('could not be loaded')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('No traversal for this agent.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Index now', exact: true })).toHaveCount(0)
})

test('switching agents discards a late indexing response', async ({ page }) => {
  let release, started
  const waiting = new Promise(resolve => { started = resolve })
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/file-share/indexing?*', async route => {
    const agent = new URL(route.request().url()).searchParams.get('agent_id')
    if (agent === '7') { started(); await gate }
    return route.fulfill({ json: { runs: [{ id: agent, root_uri: `scan-test://agent-${agent}/`, status: 'success', scanned: 1, directories: 1, error_type: null }], total: 1, pending_repairs: 0, failed_repairs: 0 } })
  })
  await mount(page, 'app/dream/components/FileIndexPanel.vue', { props: { agentId: 7, editable: false } })
  await waiting
  await page.evaluate(() => window.testApp.setProps({ agentId: 8 }))
  await expect(page.getByText('scan-test://agent-8/', { exact: true })).toBeVisible()
  release()
  await expect(page.getByText('scan-test://agent-7/', { exact: true })).toHaveCount(0)
})

test('a manager can explicitly retry terminal observation failures', async ({ page }) => {
  let failed = 1, retries = 0
  await page.route('**/api/file-share/indexing?*', route => route.fulfill({ json: { runs: [], total: 0, pending_repairs: 1 - failed, failed_repairs: failed } }))
  await page.route('**/api/file-share/indexing/repairs/retry?*', route => {
    expect(new URL(route.request().url()).searchParams.get('agent_id')).toBe('7')
    failed = 0; retries++
    return route.fulfill({ json: { retried: 1 } })
  })
  await mount(page, 'app/dream/components/FileIndexPanel.vue', { props: { agentId: 7, editable: true } })
  await page.getByRole('button', { name: 'Retry repairs', exact: true }).click()
  await expect.poll(() => retries).toBe(1)
  await expect(page.getByText('Pending repairs: 1; failed: 0.', { exact: true })).toBeVisible()
})
