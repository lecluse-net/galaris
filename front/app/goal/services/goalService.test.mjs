import assert from 'node:assert/strict'
import test from 'node:test'
import { serviceRecorder } from '../../../test-support/service-recorder.mjs'

for (const [method, suffix] of [['pause', 'pause'], ['resume', 'resume'], ['complete', 'complete'], ['runNow', 'run-now']]) {
  test(`goal ${method} preserves optimistic concurrency and uses the lifecycle endpoint`, async () => {
    const { service, requests, response } = serviceRecorder(new URL('./goalService.ts', import.meta.url), 'goalService')
    const command = { expected_revision: 8 }
    assert.equal(await service[method]('goal-a', command), response)
    assert.deepEqual(requests, [{ method: 'post', args: [`/goals/goal-a/${suffix}`, command] }])
  })
}
