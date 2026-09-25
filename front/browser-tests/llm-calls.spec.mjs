import { test, expect, mount, jsonRoute } from './fixtures.mjs'
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
