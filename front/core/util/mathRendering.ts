import DOMPurify from 'dompurify'

export type MathKind = 'inline' | 'block'
export const mathSelector = 'span[data-math="inline"], p[data-math="block"]'
let runtime: Promise<typeof import('./mathliveRuntime')> | undefined

export function loadMathLive(): Promise<typeof import('./mathliveRuntime')> {
  return runtime ??= import('./mathliveRuntime').catch(error => { runtime = undefined; throw error })
}

/** Render only explicit formula nodes, never dollar-delimited prose or code. */
export async function renderMath(root: ParentNode): Promise<void> {
  const formulas = [...root.querySelectorAll<HTMLElement>(mathSelector)].map(element => ({ element, latex: element.dataset.mathSource ?? element.textContent ?? '' }))
  if (!formulas.length) return
  const { convertLatexToMarkup } = await loadMathLive()
  for (const { element, latex } of formulas) {
    element.dataset.mathSource = latex
    element.setAttribute('aria-label', latex)
    if (latex.length > 10_000) continue
    element.innerHTML = DOMPurify.sanitize(convertLatexToMarkup(latex, { defaultMode: element.dataset.math === 'block' ? 'math' : 'inline-math' }), {
      ALLOWED_TAGS: ['span', 'svg', 'path', 'g', 'line', 'rect', 'circle', 'ellipse', 'polygon', 'polyline'],
      ALLOWED_ATTR: ['class', 'style', 'width', 'height', 'viewBox', 'd', 'fill', 'stroke', 'stroke-width', 'preserveAspectRatio', 'xmlns', 'x', 'y', 'x1', 'x2', 'y1', 'y2', 'points', 'transform', 'aria-hidden'],
      ALLOW_DATA_ATTR: false,
    })
    for (const styled of element.querySelectorAll<HTMLElement>('[style]')) {
      for (const property of [...styled.style]) {
        if (/url\s*\(|expression\s*\(|@import/i.test(styled.style.getPropertyValue(property))) styled.style.removeProperty(property)
      }
    }
  }
}

/** Embed fonts for exports rendered with network access disabled. */
export async function mathSnapshotStyles(root: ParentNode, signal: AbortSignal): Promise<string> {
  if (!root.querySelector(mathSelector)) return ''
  const { staticCss, fontsCss } = await loadMathLive()
  // static.css also imports font declarations. Embed every declaration so an
  // earlier duplicate cannot trigger a blocked request in the print sandbox.
  const css = staticCss + '\n' + fontsCss
  const urls = [...new Set([...css.matchAll(/url\(["']?([^"')]+)["']?\)/g)].map(match => match[1]!))]
  const resources = await Promise.all(urls.map(async url => {
    if (url.startsWith('data:')) return [url, url] as const
    const response = await fetch(url, { signal })
    if (!response.ok) throw new Error('Math font unavailable')
    const blob = await response.blob()
    const data = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = () => reject(reader.error)
      reader.readAsDataURL(blob)
    })
    signal.throwIfAborted()
    return [url, data] as const
  }))
  let embedded = css
  for (const [url, data] of resources) embedded = embedded.replaceAll(url, data)
  const notices = await Promise.all(['mathlive', 'katex-fonts'].map(async name => {
    const response = await fetch(`/licenses/${name}.txt`, { signal })
    if (!response.ok) throw new Error('Math license notice unavailable')
    return (await response.text()).replaceAll('*/', '* /').replaceAll('<', '\\3c ')
  }))
  signal.throwIfAborted()
  return '/*\n' + notices.join('\n\n') + '\n*/\n' + embedded
}
