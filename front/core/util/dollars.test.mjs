import assert from 'node:assert/strict'
import { test } from 'node:test'
import { formatDollars } from './dollars.ts'

test('US-dollar amounts use only the dollar symbol and preserve localized numbers', () => {
  assert.equal(formatDollars(2.5, 'en'), '$2.50')
  assert.match(formatDollars(2.5, 'fr-CA'), /^2,50\s\$$/)

  const arabic = formatDollars(2.5, 'ar-EG')
  assert.match(arabic, /٢٫٥٠/)
  assert.equal(arabic.replace(/[\p{Number}\p{Punctuation}\p{Separator}\p{Cf}]/gu, ''), '$')

  const cost = { minimumFractionDigits: 6, maximumFractionDigits: 6 }
  assert.equal(formatDollars(-0.000123, 'en', cost), '-$0.000123')
})
