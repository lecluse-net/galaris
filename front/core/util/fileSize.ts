/** Display sizes in decimal megabytes; API units stay explicit at each boundary. */
export type FileSizeUnit = 'bytes' | 'mebibytes'
const BYTES_PER_MEGABYTE = 1_000_000
const BYTES_PER_MEBIBYTE = 1_048_576

export function sizeInMegabytes(value: number, unit: FileSizeUnit = 'bytes'): number {
  return value * (unit === 'mebibytes' ? BYTES_PER_MEBIBYTE : 1) / BYTES_PER_MEGABYTE
}

export function sizeFromMegabytes(value: number, unit: FileSizeUnit = 'bytes'): number {
  const bytes = Math.round(value * BYTES_PER_MEGABYTE)
  return unit === 'mebibytes' ? bytes / BYTES_PER_MEBIBYTE : bytes
}

export function formatFileSize(bytes: number, locale = 'en'): string {
  const value = Number.isFinite(bytes) ? Math.max(0, bytes) : 0
  return new Intl.NumberFormat(locale, {
    style: 'unit', unit: 'megabyte', maximumFractionDigits: 6,
  }).format(sizeInMegabytes(value))
}
