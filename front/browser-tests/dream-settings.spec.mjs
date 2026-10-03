import { test, expect, mount, setPrivileges } from './fixtures.mjs'

test('Dream file rescanning and attachment options persist, restore after errors and honor edit rights', async ({ page }) => {
  const kinds = ['TEXT', 'DOCUMENT', 'IMAGE', 'VIDEO']
  const params = kinds.map(kind => ({ name: `DREAM_ATTACHMENT_${kind}_ENABLED`, value: 'false', secret: false, configured: true }))
  params.push({ name: 'DREAM_FILE_RESCAN_SCHEDULE', value: 'weekly_midnight', secret: false, configured: true })
  const requests = []
  let fail = false
  await page.route('**/api/memory/link-reconciliation', route => route.fulfill({ json: {
    after_dream_enabled: false, scheduled_enabled: false, interval_hours: 24,
    next_scheduled_at: null, last_completed_at: null, latest_job_status: null,
  } }))
  await page.route('**/api/params/DREAM_*', route => {
    const name = route.request().url().split('/').at(-1)
    const body = route.request().postDataJSON()
    requests.push({ name, value: body.value })
    if (fail) return route.fulfill({ status: 500, json: { detail: 'Temporary failure' } })
    const param = params.find(item => item.name === name)
    param.value = body.value
    return route.fulfill({ json: { ...param, status: 'ok' } })
  })
  await mount(page, 'core/params/components/DreamSettingsPanel.vue', { privileges: ['PARAMS_EDIT'] })
  const restore = async () => page.evaluate(params => window.testApp.patchStore('core/params/stores/paramsStore.ts', 'useParamsStore', { params }), params)
  await restore()
  // Target the attachment labels: other Dream settings remain independent.
  const labels = [
    'Summarize text attachments and documents convertible to text',
    'Describe documents without extractable text',
    'Describe images with the vision model',
    'Summarize videos from their audio track',
  ]
  for (const label of labels) await expect(page.getByRole('checkbox', { name: label, exact: true })).not.toBeChecked()
  for (let index = 0; index < labels.length; index++) {
    const checkbox = page.getByRole('checkbox', { name: labels[index], exact: true })
    await checkbox.click()
    await expect(checkbox).toBeChecked()
    await expect.poll(() => requests.at(-1)).toEqual({ name: params[index].name, value: 'true' })
  }
  const rescan = page.getByRole('combobox', { name: 'File rescanning', exact: true })
  await expect(rescan.locator('..')).toContainText('Every Monday at midnight')
  await rescan.click()
  await page.getByRole('option', { name: 'Every day at midnight', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toEqual({ name: 'DREAM_FILE_RESCAN_SCHEDULE', value: 'daily_midnight' })
  await page.evaluate(() => window.testApp.unmount())
  await page.evaluate(() => window.testApp.mount({ component: 'core/params/components/DreamSettingsPanel.vue', privileges: ['PARAMS_EDIT'] }))
  await restore()
  for (const label of labels) await expect(page.getByRole('checkbox', { name: label, exact: true })).toBeChecked()
  await expect(rescan.locator('..')).toContainText('Every day at midnight')
  fail = true
  await rescan.click()
  await page.getByRole('option', { name: 'Disabled', exact: true }).click()
  await expect.poll(() => requests.at(-1)).toEqual({ name: 'DREAM_FILE_RESCAN_SCHEDULE', value: 'off' })
  await expect(rescan.locator('..')).toContainText('Every day at midnight')
  const image = page.getByRole('checkbox', { name: labels[2], exact: true })
  await image.click()
  await expect.poll(() => requests.at(-1)).toEqual({ name: params[2].name, value: 'false' })
  await expect(image).toBeChecked()
  await setPrivileges(page, [])
  // A disabled Quasar select has no combobox input. Its field exposes the denial.
  await expect(page.locator('label').filter({ has: page.getByText('File rescanning', { exact: true }) })).toHaveAttribute('aria-disabled', 'true')
  for (const label of labels) await expect(page.getByRole('checkbox', { name: label, exact: true })).toBeDisabled()
})
