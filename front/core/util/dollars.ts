export function formatDollars(value: number, locale: string | undefined, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(locale, {
    ...options,
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
  }).formatToParts(value).map(part => part.type === 'currency' ? '$' : part.value).join('')
}
