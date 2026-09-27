import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'
import { call } from './data.mjs'

test('call origin shows the API token and preserves unnamed, historical and agent origins', async ({ page }) => {
  await jsonRoute(page, '**/api/llm-providers/llms*', [])
  const tokenCall = { ...call, purpose: null, api_token_label: 'External coding client', response_text: 'A preserved response' }
  await mount(page, 'app/llm/components/LlmCall.vue', { props: {
    call: tokenCall, taskColor: { name: 'primary', hex: '#087FF5' },
  } })
  const title = page.locator('.agent-title')
  await expect(title).toContainText('API token: External coding client')
  await page.getByRole('button', { name: 'Details', exact: true }).click()
  await expect(page.getByRole('paragraph').filter({ hasText: /^A preserved response$/ })).toBeVisible()
  await page.evaluate(data => window.testApp.setProps({ call: { ...data, api_token_label: '' } }), tokenCall)
  await expect(title).toContainText('Unnamed API token')
  await page.evaluate(data => window.testApp.setProps({ call: { ...data, api_token_label: null } }), tokenCall)
  await expect(title).toContainText('Galaris internal service')
  await page.evaluate(data => window.testApp.setProps({ call: {
    ...data, api_token_label: null, agent_id: 7, agent_name: 'Alice Example', task_label: 'Review a document',
  } }), tokenCall)
  await expect(title).toContainText('Alice Example')
  await expect(title).toContainText('Review a document')
  await expect(title).not.toContainText('API token')
  await page.evaluate(data => window.testApp.setProps({ call: {
    ...data, agent_id: 7, agent_name: 'Alice Example', task_label: 'Review a document',
  } }), tokenCall)
  await expect(title).toContainText('Alice Example')
  await expect(page.getByText('API token: External coding client', { exact: true })).toBeVisible()
})

for (const component of ['LlmCall', 'LlmCallTaskDetail']) {
  test(`${component}: stopping a durable call keeps its trace and supports retry`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await jsonRoute(page, '**/api/llm-providers/llms*', [])
    const running = { ...call, status: 'running', inference_attempt_id: '00000000-0000-4000-8000-000000000001' }
    let requests = 0
    await page.route(`**/api/llm-calls/${call.id}/stop`, async route => {
      expect(route.request().method()).toBe('POST')
      requests += 1
      await route.fulfill({ status: requests === 1 ? 503 : 202, json: null })
    })
    await mount(page, `app/llm/components/${component}.vue`, { props: {
      call: running, deletable: true, taskColor: { name: 'primary', hex: '#087FF5' },
    }, privileges: ['TASK_ACCESS', 'LLM_CALL_PURGE'] })
    const stop = page.getByRole('button', { name: 'Stop this LLM call', exact: true })
    await expect(stop).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Delete this LLM call' })).toHaveCount(0)
    await setPrivileges(page, ['TASK_EDIT', 'LLM_CALL_PURGE'])
    await stop.focus()
    await page.keyboard.press('Enter')
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    expect(requests).toBe(0)
    await stop.click()
    await page.getByRole('dialog').getByRole('button', { name: 'Stop this LLM call' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect(page.getByText('Could not request this LLM call to stop. Try again.')).toBeVisible()
    await stop.click()
    await page.getByRole('dialog').getByRole('button', { name: 'Stop this LLM call' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect(page.getByText('Stop requested. The call stays visible until the worker confirms it.')).toBeVisible()
    await expect(stop).toBeVisible()
    expect(requests).toBe(2)
    await page.evaluate(data => window.testApp.setProps({ call: { ...data, status: 'cancelled' } }), running)
    await expect(stop).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Delete this LLM call' })).toHaveCount(0)
    await page.evaluate(data => window.testApp.setProps({ call: { ...data, status: 'completed', inference_attempt_id: null } }), running)
    await expect(page.getByRole('button', { name: 'Delete this LLM call' })).toBeVisible()
  })
}
