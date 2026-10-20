import { test, expect, mount, jsonRoute } from './fixtures.mjs'

for (const width of [390, 1440]) {
  test(`metric cards preserve values and expose optional mouse and keyboard actions at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await mount(page, 'core/util/components/MetricCard.vue', {
      props: { label: 'Errors', value: 7, icon: 'error', tone: 'red' },
    })
    await expect(page.getByText('7', { exact: true })).toBeVisible()
    await expect(page.getByRole('button')).toHaveCount(0)
    await page.getByText('Errors', { exact: true }).click()
    expect(await page.evaluate(() => window.testApp.events)).toEqual([])

    await page.evaluate(() => window.testApp.setProps({ interactive: true }))
    const metric = page.getByRole('button', { name: /Errors.*7/ })
    await expect(metric).toHaveAttribute('aria-pressed', 'false')
    for (const [index, action] of ['click', 'Enter', 'Space'].entries()) {
      if (action === 'click') await metric.click()
      else await metric.press(action)
      expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'activate').length)).toBe(index + 1)
    }
    await page.evaluate(() => window.testApp.setProps({ active: true }))
    await expect(metric).toHaveAttribute('aria-pressed', 'true')
    for (const dark of [false, true]) {
      await page.evaluate(dark => window.testApp.dark(dark), dark)
      await page.screenshot({ path: testInfo.outputPath(`metric-${width}-${dark ? 'dark' : 'light'}.png`) })
    }
    await page.evaluate(() => window.testApp.setProps({ loading: true }))
    await expect(page.getByRole('button', { name: 'Errors', exact: true })).toHaveAttribute('aria-busy', 'true')
    await page.evaluate(() => window.testApp.setProps({ loading: false, value: 0 }))
    await expect(page.getByRole('button', { name: /Errors.*0/ })).toBeVisible()
  })
}

for (const [kind, component, endpoint, summary, parameter] of [
  ['text', 'app/conversation/components/ConversationHistory.vue', '/conversations/messages', { idle: 2, ready: 3, running: 5, errors: 7 }, 'errors_only'],
  ['voice', 'app/voice/components/VoiceCallHistory.vue', '/voice/conversations', { completed: 2, cancelled: 3, active: 5, errors: 7 }, 'status'],
]) {
  test(`${kind} history metric and toolbar actions preserve domain filters and can clear them`, async ({ page }, testInfo) => {
    const requests = []
    await jsonRoute(page, '**/api/agents?*', [])
    await page.route(`**/api${endpoint}?*`, route => {
      requests.push(new URL(route.request().url()).searchParams)
      return route.fulfill({ json: { items: [], page: 1, page_size: 50, total: 0, summary } })
    })
    await mount(page, component)
    const errors = page.getByRole('button', { name: /errors.*7/i })
    await errors.click()
    await expect(errors).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(() => requests.at(-1)?.get(parameter)).toBe(kind === 'text' ? 'true' : 'ERROR')
    const search = page.getByRole('textbox', { name: kind === 'text' ? 'Search a message, conversation, or participant' : 'Search rooms and transcripts', exact: true })
    await search.fill('synthetic search')
    await expect.poll(() => requests.at(-1)?.get('search')).toBe('synthetic search')
    expect(requests.at(-1)?.get(parameter)).toBe(kind === 'text' ? 'true' : 'ERROR')
    await page.getByLabel('From', { exact: true }).fill('2026-01-02')
    await expect.poll(() => requests.at(-1)?.get('date_from')).toBe('2026-01-02')
    await page.screenshot({ path: testInfo.outputPath(`${kind}-history-desktop.png`) })
    await page.setViewportSize({ width: 390, height: 900 })
    await page.evaluate(() => window.testApp.dark(true))
    await errors.press('Space')
    await expect(errors).toHaveAttribute('aria-pressed', 'false')
    await expect.poll(() => requests.at(-1)?.get(parameter)).toBeNull()
    await search.fill('')
    await expect.poll(() => requests.at(-1)?.get('search')).toBeNull()
    await page.getByRole('button', { name: 'Clear date range', exact: true }).press('Enter')
    await expect.poll(() => requests.at(-1)?.get('date_from')).toBeNull()
    await page.screenshot({ path: testInfo.outputPath(`${kind}-history-mobile-dark.png`) })
  })
}
