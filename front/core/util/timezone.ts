/** Local wall-clock conversion shared by agenda events and Goal planning. */
export function wallTime(instant: string | Date, timezone: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(instant))
  const value = (key: string) => parts.find(part => part.type === key)?.value ?? ''
  return `${value('year')}-${value('month')}-${value('day')}T${value('hour')}:${value('minute')}`
}
/** Resolve independently of the browser timezone; reject nonexistent DST hours. */
export function zonedInstant(wall: string, timezone: string): string {
  const target = Date.parse(`${wall}:00Z`)
  if (!Number.isFinite(target)) throw new Error('invalidDate')
  let guess = target
  for (let index = 0; index < 4; index++) {
    const observed = Date.parse(`${wallTime(new Date(guess), timezone)}:00Z`)
    const delta = target - observed
    if (!delta) return new Date(guess).toISOString()
    guess += delta
  }
  throw new Error('invalidDate')
}
