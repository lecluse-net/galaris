/** Portable static copy of an already authorized, rendered application component. */
export async function captureElementRendering(element: HTMLElement, signal: AbortSignal): Promise<string> {
  signal.throwIfAborted()
  await element.ownerDocument.fonts.ready
  await Promise.all([...element.querySelectorAll('img')].map(image => image.decode()))
  signal.throwIfAborted()
  let count = 0, bytes = 0
  async function copy(source: Node): Promise<Node | null> {
    signal.throwIfAborted()
    if (++count > 10000) throw new Error('Rendering too large')
    if (source.nodeType === Node.TEXT_NODE) return document.importNode(source, false)
    if (!(source instanceof Element) || source.matches('script, style, iframe, .q-icon, .q-tooltip, .q-focus-helper, .q-ripple')) return null
    const target = source.tagName === 'BUTTON' ? document.createElement('div') : source.cloneNode(false) as HTMLElement | SVGElement
    for (const attr of [...target.attributes]) {
      if (!['id', 'viewBox', 'd', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'width', 'height', 'rx', 'ry', 'cx', 'cy', 'r', 'points', 'xmlns', 'markerWidth', 'markerHeight', 'refX', 'refY', 'orient'].includes(attr.name)) target.removeAttribute(attr.name)
    }
    const style = getComputedStyle(source)
    for (const property of style) target.style.setProperty(property, style.getPropertyValue(property).replace(/url\(["']?[^)'"#]*#([^)'"\s]+)["']?\)/g, 'url(#$1)'))
    target.style.setProperty('animation', 'none'); target.style.setProperty('transition', 'none'); target.style.setProperty('outline', 'none')
    if (source instanceof HTMLImageElement) {
      const uri = source.currentSrc || source.src
      if (!/^(?:blob:|data:image\/)/.test(uri)) throw new Error('Rendering image must already be materialized')
      const response = await fetch(uri, { signal })
      if (!response.ok) throw new Error('Rendering image unavailable')
      const blob = await response.blob(); bytes += blob.size
      if (bytes > 8_000_000 || !/^image\/(png|jpeg|gif|webp)$/.test(blob.type)) throw new Error('Invalid rendering image')
      const reader = new FileReader()
      target.setAttribute('src', await new Promise<string>((resolve, reject) => {
        reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('Rendering image unavailable'))
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(blob)
      }))
    } else for (const child of source.childNodes) { const node = await copy(child); if (node) target.append(node) }
    return target
  }
  const root = await copy(element) as HTMLElement
  signal.throwIfAborted()
  root.style.position = 'relative'; root.style.inset = 'auto'; root.style.margin = '0'
  root.style.transform = 'none'; root.style.zoom = '1'
  root.style.width = element.offsetWidth + 'px'; root.style.height = element.offsetHeight + 'px'
  return root.outerHTML
}
