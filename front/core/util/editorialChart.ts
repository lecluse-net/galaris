export const chartKinds = ['bar', 'line', 'pie'] as const
export const maxChartRows = 20
export const maxChartLabel = 60
export const maxChartTitle = 100
export const chartAttribute = 'data-galaris-chart'
export const chartSelector = `figure[${chartAttribute}]`

export interface EditorialChart {
  version: 1
  type: typeof chartKinds[number]
  title: string
  rows: { label: string; value: number }[]
}

export function isEditorialChart(value: unknown): value is EditorialChart {
  if (!value || typeof value !== 'object') return false
  const { version, type, title, rows } = value as Partial<EditorialChart>
  if (version !== 1 || !type || !chartKinds.includes(type) || typeof title !== 'string'
    || Array.from(title).length > maxChartTitle || !Array.isArray(rows) || !rows.length || rows.length > maxChartRows) return false
  if (!rows.every(row => row && typeof row.label === 'string' && row.label.trim()
    && Array.from(row.label).length <= maxChartLabel && Number.isFinite(row.value) && Math.abs(row.value) <= 1e15)) return false
  return type !== 'pie' || rows.every(row => row.value >= 0) && rows.some(row => row.value > 0)
}

function decodeChart(encoded: string | null): EditorialChart | null {
  if (!encoded || encoded.length > 30_000) return null
  try {
    const value: unknown = JSON.parse(decodeURIComponent(encoded))
    return isEditorialChart(value) ? value : null
  } catch {
    return null
  }
}

export function readEditorialChart(source: unknown): EditorialChart | null {
  if (typeof source !== 'string') return null
  const template = document.createElement('template')
  template.innerHTML = source
  const svg = template.content.firstElementChild
  return svg?.localName === 'svg' && svg.namespaceURI === 'http://www.w3.org/2000/svg'
    ? decodeChart(svg.getAttribute(chartAttribute)) : null
}

export function readChartFigure(figure: Element): EditorialChart | null {
  if (!figure.matches(chartSelector) || figure.childElementCount > 1
    || [...figure.childNodes].some(child => child.nodeType === 3 && child.textContent?.trim())) return null
  const caption = figure.firstElementChild
  if (caption && (caption.localName !== 'figcaption' || caption.childElementCount)) return null
  return decodeChart(figure.getAttribute(chartAttribute))
}

export function encodeEditorialChart(chart: EditorialChart): string {
  return encodeURIComponent(JSON.stringify(chart)).replaceAll('(', '%28')
}

export function chartCaption(chart: EditorialChart): string {
  return [chart.title, ...chart.rows.map(({ label, value }) => `${label} ${value}`)].filter(Boolean).join(' · ')
}
