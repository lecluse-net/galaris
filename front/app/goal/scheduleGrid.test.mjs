import assert from 'node:assert/strict'
import test from 'node:test'

import {
  goalScheduleDefaultSlots,
  goalScheduleSlotsToWindows,
  goalScheduleWindowsToSlots,
} from './scheduleGrid.ts'

test('a fully enabled week serializes without zero-length windows and round-trips', () => {
  const slots = goalScheduleDefaultSlots()
  const windows = goalScheduleSlotsToWindows(slots)

  assert.equal(slots.size, 7 * 24)
  assert.equal(windows.length, 2)
  assert.deepEqual(windows.map(window => [window.start_time, window.end_time]), [
    ['00:00', '12:00'],
    ['12:00', '00:00'],
  ])
  assert.ok(windows.every(window => window.start_time !== window.end_time))
  assert.deepEqual(goalScheduleWindowsToSlots(windows), slots)
})
