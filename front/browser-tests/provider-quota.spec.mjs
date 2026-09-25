import { test, expect, mount } from './fixtures.mjs'

const snapshot = (percent = 37) => ({
  windows: [
    { name: 'primary', used_percent: percent, window_seconds: 18000, resets_at: '2033-05-18T03:33:20Z' },
    { name: 'secondary', used_percent: 0, window_seconds: 604800, resets_at: null },
  ],
  checked_at: '2033-05-18T02:00:00Z',
})

test('account windows load, refresh, and recover from unavailable quotas', async ({ page }) => {
  let response = snapshot()
  let status = 200
  await page.route('**/api/llm-providers/17/quota', route => route.fulfill({ status, json: response }))
  await mount(page, 'app/llm/components/ProviderQuotaPanel.vue', { props: { providerId: 17 } })
  await expect(page.getByText('37% used', { exact: true })).toBeVisible()
  await expect(page.getByText('0% used', { exact: true })).toBeVisible()
  await expect(page.getByText('Over 5 h', { exact: true })).toBeVisible()
  await expect(page.getByText('Over 7 d', { exact: true })).toBeVisible()
  await expect(page.getByText(/^Resets:/)).toBeVisible()
  response = snapshot(100)
  await page.getByRole('button', { name: 'Refresh limits' }).click()
  await expect(page.getByText('100% used', { exact: true })).toBeVisible()
  status = 502
  await page.getByRole('button', { name: 'Refresh limits' }).click()
  await expect(page.getByRole('alert')).toContainText('Limits unavailable')
  await expect(page.getByText('100% used', { exact: true })).toHaveCount(0)
  status = 200
  response = { windows: [], checked_at: snapshot().checked_at }
  await page.getByRole('button', { name: 'Refresh limits' }).click()
  await expect(page.getByText('The provider did not report any quota windows.')).toBeVisible()
  response = snapshot(21)
  await mount(page, 'app/llm/components/ProviderQuotaPanel.vue', { props: { providerId: 17 } })
  await expect(page.getByText('21% used', { exact: true })).toBeVisible()
})

test('changing provider ignores a late response from the previous account', async ({ page }) => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/llm-providers/17/quota', async route => {
    await pending
    await route.fulfill({ json: snapshot(99) }).catch(() => {})
  })
  await page.route('**/api/llm-providers/18/quota', route => route.fulfill({ json: snapshot(12) }))
  await mount(page, 'app/llm/components/ProviderQuotaPanel.vue', { props: { providerId: 17 } })
  await expect(page.getByRole('status')).toHaveText('Loading limits…')
  await page.evaluate(() => window.testApp.setProps({ providerId: 18 }))
  await expect(page.getByText('12% used', { exact: true })).toBeVisible()
  release()
  await expect(page.getByText('99% used', { exact: true })).toHaveCount(0)
})
