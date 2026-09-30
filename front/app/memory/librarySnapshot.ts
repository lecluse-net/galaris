/** Reuse unchanged JSON records so refreshing one document leaves its neighbours alone. */
export function reconcileLibrarySnapshot<T>(previous: T[], incoming: T[], key: (value: T) => string): T[] {
  const existing = new Map(previous.map(value => [key(value), value]))
  const reconciled = incoming.map(value => {
    const current = existing.get(key(value))
    return current && JSON.stringify(current) === JSON.stringify(value) ? current : value
  })
  return previous.length === reconciled.length && reconciled.every((value, index) => value === previous[index])
    ? previous : reconciled
}
