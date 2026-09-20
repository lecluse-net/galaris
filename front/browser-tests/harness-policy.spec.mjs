import { test, expect, mount } from './fixtures.mjs'

function configuration(code, revision = 0) {
  return {
    provider_code: code, label: code, revision,
    descriptor: {
      schema_version: 'galaris.harness-capabilities/v1', revision,
      implemented: ['execute', 'streaming', 'checkpoints'], configurable: ['execute', 'streaming'],
      configured: ['execute', 'streaming', 'checkpoints'], verified: ['execute', 'streaming', 'checkpoints'],
      effective: ['execute', 'streaming', 'checkpoints'], unavailable: {},
      policy: {
        disabled_capabilities: [], max_parallel_tasks: null, execution_timeout_seconds: null,
        idle_timeout_seconds: null, stream_close_timeout_seconds: 5,
        max_message_bytes: 1000000, max_result_bytes: 16000000, max_stream_bytes: 64000000,
      },
    },
  }
}

test('shared harness settings load directly and save a revisioned configuration', async ({ page }) => {
  let loads = 0
  let saved
  await page.route('**/api/harnesses/execution-configurations', async route => {
    loads += 1
    await route.fulfill({ json: [configuration('internal'), configuration('arbitrary-runtime')] })
  })
  await page.route('**/api/harnesses/execution-configurations/internal', async route => {
    saved = route.request().postDataJSON()
    const response = configuration('internal', 1)
    response.descriptor.policy = saved.policy
    await route.fulfill({ json: response })
  })
  await mount(page, 'app/harnesses/components/HarnessExecutionSettings.vue')
  const concurrency = page.getByLabel('Maximum concurrent tasks', { exact: true })
  await concurrency.fill('3')
  await expect(concurrency).toHaveValue('3')
  const messageSize = page.getByLabel('Maximum message size (MB)', { exact: true })
  await expect(messageSize).toHaveValue('1')
  await messageSize.fill('2.5')
  expect(loads).toBe(1)
  await page.getByLabel('Disabled capabilities', { exact: true }).click()
  await expect(page.getByRole('option', { name: 'Checkpoints', exact: true })).toHaveCount(0)
  await page.getByRole('option', { name: 'Native streaming', exact: true }).click()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('Settings saved.')
  expect(saved.expected_revision).toBe(0)
  expect(saved.policy.max_parallel_tasks).toBe(3)
  expect(saved.policy.disabled_capabilities).toEqual(['streaming'])
  expect(saved.policy.max_message_bytes).toBe(2500000)
  expect(saved.policy.max_result_bytes).toBe(16000000)
  expect(saved.policy.max_stream_bytes).toBe(64000000)
  await expect(messageSize).toHaveValue('2.5')
  await concurrency.fill('4')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => saved.expected_revision).toBe(1)
  expect(saved.policy.max_message_bytes).toBe(2500000)
})

test('configuration conflicts keep edits and arbitrary providers use the same controls', async ({ page }) => {
  await page.route('**/api/harnesses/execution-configurations', route => route.fulfill({
    json: [configuration('internal'), configuration('arbitrary-runtime', 7)],
  }))
  let attempted
  await page.route('**/api/harnesses/execution-configurations/arbitrary-runtime', async route => {
    attempted = route.request().postDataJSON()
    await route.fulfill({ status: 409, json: { detail: 'Concurrent edit' } })
  })
  await mount(page, 'app/harnesses/components/HarnessExecutionSettings.vue')
  await page.getByLabel('Harness', { exact: true }).click()
  await page.getByRole('option', { name: 'arbitrary-runtime', exact: true }).click()
  await page.getByLabel('Maximum run duration (seconds)', { exact: true }).fill('120')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Save rejected')
  await expect(page.getByLabel('Maximum run duration (seconds)', { exact: true })).toHaveValue('120')
  expect(attempted.expected_revision).toBe(7)
  expect(attempted.policy.execution_timeout_seconds).toBe(120)
})
