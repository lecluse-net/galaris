import { test, expect, mount } from './fixtures.mjs'

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
    await mount(page, 'app/memory/components/FileIndexPanel.vue', { props: { agentId: 7, editable: true } })
    await page.getByText('File indexing', { exact: true }).click()
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
  await mount(page, 'app/memory/components/FileIndexPanel.vue', { props: { agentId: 7, editable: false } })
  await page.getByText('File indexing', { exact: true }).click()
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
  await mount(page, 'app/memory/components/FileIndexPanel.vue', { props: { agentId: 7, editable: false } })
  await page.getByText('File indexing', { exact: true }).click()
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
  await mount(page, 'app/memory/components/FileIndexPanel.vue', { props: { agentId: 7, editable: true } })
  await page.getByText('File indexing', { exact: true }).click()
  await page.getByRole('button', { name: 'Retry repairs', exact: true }).click()
  await expect.poll(() => retries).toBe(1)
  await expect(page.getByText('Pending repairs: 1; failed: 0.', { exact: true })).toBeVisible()
})
