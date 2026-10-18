/** Display-only correction for isolated HTML and its inert export copy.
 * Keep this function self-contained: the sandbox runs its serialized JavaScript.
 */
export function applyDocumentContrast(doc: Document, backdrop = 'rgb(255, 255, 255)'): void {
  const view = doc.defaultView
  if (!view || !doc.body) return
  let sheet = doc.querySelector<HTMLStyleElement>('style[data-galaris-contrast]')
  if (!sheet) {
    sheet = doc.createElement('style'); sheet.dataset.galarisContrast = ''
    sheet.textContent = 'html [data-galaris-readable="light"]{color:#fff!important}html [data-galaris-readable="dark"]{color:#000!important}'
    doc.head.append(sheet)
  }
  doc.querySelectorAll('[data-galaris-readable]').forEach(element => element.removeAttribute('data-galaris-readable'))
  type Color = [number, number, number, number]
  const parse = (value: string): Color | null => {
    if (!/^rgba?\(/.test(value)) return null
    const channels = value.match(/[\d.]+/g)?.map(Number)
    return channels && channels.length >= 3 ? [channels[0]!, channels[1]!, channels[2]!, channels[3] ?? 1] : null
  }
  const blend = (front: Color, back: Color): Color => [
    front[0] * front[3] + back[0] * (1 - front[3]),
    front[1] * front[3] + back[1] * (1 - front[3]),
    front[2] * front[3] + back[2] * (1 - front[3]), 1,
  ]
  const backgrounds = new Map<Element, Color>()
  function background(element: Element | null): Color {
    if (!element) return parse(backdrop) ?? [255, 255, 255, 1]
    const cached = backgrounds.get(element)
    if (cached) return cached
    const color = parse(view!.getComputedStyle(element).backgroundColor) ?? [0, 0, 0, 0]
    const result = color[3] === 1 ? color : blend(color, background(element.parentElement))
    backgrounds.set(element, result)
    return result
  }
  const luminance = (color: Color): number => color.slice(0, 3).reduce((sum, value, index) => {
    const channel = value / 255
    return sum + (channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4) * [.2126, .7152, .0722][index]!
  }, 0)
  // Parents precede their children, so inherited corrections are taken into account.
  const elements = [doc.body, ...doc.body.querySelectorAll('*')].slice(0, 10000)
  for (const element of elements) {
    if (element.namespaceURI !== 'http://www.w3.org/1999/xhtml' || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(element.tagName)) continue
    if (element !== doc.body && !['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName)
      && ![...element.childNodes].some(node => node.nodeType === 3 && node.textContent?.trim())) continue
    const style = view.getComputedStyle(element), ink = parse(style.color)
    if (!ink || ink[3] === 0 || style.visibility !== 'visible' || style.display === 'none') continue
    const surface = background(element), back = luminance(surface), front = luminance(blend(ink, surface))
    const size = parseFloat(style.fontSize), large = size >= 24 || size >= 18.66 && parseInt(style.fontWeight, 10) >= 700
    if ((Math.max(front, back) + .05) / (Math.min(front, back) + .05) >= (large ? 3 : 4.5)) continue
    element.setAttribute('data-galaris-readable', (back + .05) / .05 >= 1.05 / (back + .05) ? 'dark' : 'light')
  }
}
