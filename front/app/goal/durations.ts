export const UNIT_SECONDS = { seconds: 1, minutes: 60, hours: 3600, days: 86400, weeks: 604800, months: 2592000, years: 31536000 } as const
export type DurationUnit = keyof typeof UNIT_SECONDS
