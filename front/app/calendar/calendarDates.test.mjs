import { test } from 'node:test'
import assert from 'node:assert/strict'
import { loadTypescript } from '../../test-support/load-typescript.mjs'
const clock = loadTypescript(new URL('../../core/util/timezone.ts', import.meta.url), {})
const { addMonths, isoWeekNumber, zonedInstant, wallTime, queryWindows, visibleDays, eventOnDay, positionEvents } = loadTypescript(new URL('./calendarDates.ts', import.meta.url), { '@/core/util': clock })

test('ISO week numbers keep Monday boundaries and the week year across New Year', () => {
  for (const [day, week] of [
    ['2026-11-09', 46], ['2026-11-15', 46], ['2026-11-16', 47],
    ['2020-12-31', 53], ['2021-01-01', 53], ['2021-01-03', 53], ['2021-01-04', 1],
    ['2024-12-30', 1], ['2026-12-31', 53], ['2027-01-01', 53], ['2027-01-04', 1],
  ]) assert.equal(isoWeekNumber(day), week, day)
})

test('calendar queries cover a six-week month with bounded contiguous timezone-aware windows', () => {
  const days = visibleDays('2026-03-15', 'month'), windows = queryWindows(days, 'Europe/Paris')
  assert.equal(days.length, 42)
  assert.equal(wallTime(windows[0].start, 'Europe/Paris'), '2026-02-23T00:00')
  assert.equal(wallTime(windows.at(-1).end, 'Europe/Paris'), '2026-04-06T00:00')
  assert.equal(windows[0].end, windows[1].start)
  assert.ok(windows.every(row => Date.parse(row.end) - Date.parse(row.start) <= 32 * 86400000))
  assert.equal(addMonths('2026-01-31', 1), '2026-02-28')
})
test('event wall clocks are independent of browser timezone and reject a skipped DST hour', () => {
  assert.equal(zonedInstant('2026-07-20T09:00', 'Europe/Paris'), '2026-07-20T07:00:00.000Z')
  assert.equal(zonedInstant('2026-11-20T09:00', 'Europe/Paris'), '2026-11-20T08:00:00.000Z')
  assert.throws(() => zonedInstant('2026-03-29T02:30', 'Europe/Paris'), /invalidDate/)
  assert.equal(wallTime(zonedInstant('2026-10-25T02:30', 'Europe/Paris'), 'Europe/Paris'), '2026-10-25T02:30')
})
test('all-day and timed events respect exclusive ends and simultaneous events remain independently usable', () => {
  const allDay = { all_day: true, start_date: '2026-11-12', end_date: '2026-11-14' }
  assert.ok(eventOnDay(allDay, '2026-11-13', 'America/New_York'))
  assert.ok(!eventOnDay(allDay, '2026-11-14', 'America/New_York'))
  const make = (start, end) => ({ all_day: false, start: `2026-11-12T${start}:00Z`, end: `2026-11-12T${end}:00Z` })
  const events = [make('09:00', '10:00'), make('09:30', '11:00'), make('11:00', '12:00')]
  const rows = positionEvents(events, '2026-11-12', 'UTC')
  assert.deepEqual(rows.map(row => [row.column, row.columns]), [[0, 2], [1, 2], [0, 1]])
  assert.ok(!eventOnDay(make('00:00', '01:00'), '2026-11-11', 'UTC'))
})
test('overlap groups reuse free columns, expand into free space and include the visible duration of short events', () => {
  const make = (id, start, end) => ({ event_id: id, recurrence_key: '', all_day: false, start: `2026-11-12T${start}:00Z`, end: `2026-11-12T${end}:00Z` })
  const events = [make('long', '09:00', '12:00'), make('one', '09:00', '10:00'), make('two', '09:00', '10:00'), make('later', '10:00', '11:00')]
  const rows = positionEvents(events, '2026-11-12', 'UTC')
  const later = rows.find(row => row.event.event_id === 'later')
  assert.equal(later.columns, 3)
  assert.equal(later.span, 2)
  assert.deepEqual(positionEvents([...events].reverse(), '2026-11-12', 'UTC'), rows)
  const short = positionEvents([make('first', '09:00', '09:05'), make('next', '09:10', '09:15'), make('last', '23:55', '23:59')], '2026-11-12', 'UTC')
  assert.notEqual(short[0].column, short[1].column)
  assert.ok(short.every(row => row.top + row.height <= 1440))
  for (const positions of [rows, short]) {
    for (const [index, a] of positions.entries()) for (const b of positions.slice(index + 1)) {
      const vertical = a.top < b.top + b.height && b.top < a.top + a.height
      const horizontal = a.column / a.columns < (b.column + b.span) / b.columns && b.column / b.columns < (a.column + a.span) / a.columns
      assert.ok(!vertical || !horizontal, `${a.event.event_id} obscures ${b.event.event_id}`)
    }
  }
})
