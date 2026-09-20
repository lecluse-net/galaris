import assert from 'node:assert/strict'
import test from 'node:test'
import { formatFileSize, sizeInMegabytes, sizeFromMegabytes } from './fileSize.ts'

test('editing sizes in decimal megabytes preserves existing byte and legacy binary limits', () => {
  for (const value of [0, 1, 1024, 65536, 20971520, 1048576000]) {
    assert.equal(sizeFromMegabytes(sizeInMegabytes(value)), value)
  }
  for (const value of [1, 4, 512, 10240]) {
    assert.equal(sizeFromMegabytes(sizeInMegabytes(value, 'mebibytes'), 'mebibytes'), value)
  }
  assert.equal(sizeFromMegabytes(0.3), 300000)
  assert.equal(sizeFromMegabytes(2.5), 2500000)
})

test('small and large files always use localized megabytes without rounding small files to zero', () => {
  assert.match(formatFileSize(1, 'fr'), /0,000001.*Mo/)
  assert.match(formatFileSize(65536, 'fr'), /0,065536.*Mo/)
  assert.match(formatFileSize(2500000, 'en'), /2\.5.*MB/)
  assert.match(formatFileSize(5000000000, 'en'), /5,000.*MB/)
  assert.match(formatFileSize(0, 'fr'), /0.*Mo/)
})
