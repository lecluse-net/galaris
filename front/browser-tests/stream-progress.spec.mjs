import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { call as baseCall } from './data.mjs'

test('LLM trace deltas preserve context, recover one missing batch and ignore late progress after completion', async ({ page }) => {
  const call = { ...baseCall, id: 'synthetic-call', task_id: 'synthetic-task', requested_model: 'Synthetic model',
    effective_model: 'Synthetic model', provider_name: 'Synthetic provider', purpose: 'agent.exec',
    status: 'running', response_text: 'Initial🙂', reasoning: '', tool_calls: [], request_messages: [],
    prompt: 'Synthetic retained context', system_prompt: '', raw_response: '', usage: {}, cost: 0,
    inference_cost: 0, total_tokens: 0, started_at: '2026-01-01T12:00:00Z',
    updated_at: '2026-01-01T12:00:00.000001Z' }
  await jsonRoute(page, '**/api/llm-calls?task_id=synthetic-task', [call])
  await jsonRoute(page, '**/api/llm-providers/llms', [])
  let release, reads = 0
  await page.route('**/api/llm-calls/synthetic-call', async route => {
    reads++
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { ...call, response_text: 'Recovered🙂漢字', updated_at: '2026-01-01T12:00:00.000004Z' } })
  })
  await mount(page, 'app/llm/components/LlmCalls.vue', { props: { taskId: 'synthetic-task' } })
  const preview = page.getByRole('button', { name: 'Expand', exact: true })
  await expect(preview).toContainText('Initial🙂')
  const emit = data => page.evaluate(data => window.testApp.emitSocket('llm_call.progress', { data }), data)
  await emit({ id: call.id, base_updated_at: call.updated_at, updated_at: '2026-01-01T12:00:00.000002Z',
    response_text: { append: '漢字' }, reasoning: { append: '' } })
  await expect(preview).toContainText('Initial🙂漢字')
  const gap = { id: call.id, base_updated_at: '2026-01-01T12:00:00.000003Z',
    updated_at: '2026-01-01T12:00:00.000004Z', response_text: { append: 'Lost base' }, reasoning: { append: '' } }
  await emit(gap)
  await emit(gap)
  await expect.poll(() => reads).toBe(1)
  release()
  await expect(preview).toContainText('Recovered🙂漢字')
  await page.evaluate(call => window.testApp.emitSocket('llm_call.update', { data: { ...call,
    status: 'completed', response_text: 'Terminal answer', updated_at: '2026-01-01T12:00:00.000005Z' } }), call)
  await emit(gap)
  await expect(preview).toContainText('Terminal answer')
  expect(reads).toBe(1)
})
