export function agentResourceId(uri: string): number | null {
  const match = /^galaris:\/\/agent\/([1-9][0-9]*)$/.exec(uri)
  const id = match ? Number(match[1]) : NaN
  return Number.isSafeInteger(id) ? id : null
}
