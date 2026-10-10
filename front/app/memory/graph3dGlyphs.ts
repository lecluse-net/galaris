import { CanvasTexture, LinearFilter, SRGBColorSpace } from 'three'

/** A single bounded texture for the same public SVG assets and Material paths
 * used by the 2D graph. Nothing here loads an authorized resource thumbnail. */
export class Graph3dGlyphs {
  readonly texture: CanvasTexture
  private readonly canvas = document.createElement('canvas')
  private readonly context: CanvasRenderingContext2D
  private readonly entries = new Map<string, { index: number; colored: number }>()
  private readonly pending = new Set<HTMLImageElement>()
  private disposed = false

  constructor(private readonly repaint: () => void) {
    this.canvas.width = this.canvas.height = 1024
    this.context = this.canvas.getContext('2d')!
    this.texture = new CanvasTexture(this.canvas)
    this.texture.colorSpace = SRGBColorSpace
    this.texture.minFilter = this.texture.magFilter = LinearFilter
    this.texture.generateMipmaps = false
  }

  get(symbol: string): { index: number; colored: number } {
    const existing = this.entries.get(symbol)
    if (existing) return existing
    if (this.entries.size >= 64) throw new Error('Memory graph glyph atlas capacity exceeded')
    const entry = { index: this.entries.size, colored: Number(symbol.startsWith('image://')) }
    this.entries.set(symbol, entry)
    const image = new Image()
    this.pending.add(image)
    image.onload = () => {
      this.pending.delete(image)
      if (this.disposed) return
      this.context.drawImage(image, entry.index % 8 * 128, Math.floor(entry.index / 8) * 128, 128, 128)
      this.texture.needsUpdate = true
      this.repaint()
    }
    image.onerror = () => {
      this.pending.delete(image)
      // Keep a file glyph if a public asset is unavailable; never replace it by
      // an opaque square, and do not retry a failed asset on every camera frame.
      if (this.disposed) return
      const x = entry.index % 8 * 128, y = Math.floor(entry.index / 8) * 128
      this.context.strokeStyle = '#ffffff'
      this.context.lineWidth = 6
      this.context.strokeRect(x + 28, y + 12, 72, 104)
      this.texture.needsUpdate = true
      this.repaint()
    }
    if (entry.colored) image.src = symbol.slice('image://'.length)
    else image.src = this.pathImage(symbol.slice('path://'.length))
    return entry
  }

  private pathImage(data: string): string {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', data)
    path.setAttribute('fill', '#ffffff')
    svg.append(path)
    Object.assign(svg.style, { position: 'absolute', width: '0', height: '0', visibility: 'hidden', pointerEvents: 'none' })
    svg.setAttribute('aria-hidden', 'true')
    document.body.append(svg)
    const box = path.getBBox()
    svg.remove()
    svg.removeAttribute('style')
    svg.setAttribute('viewBox', `${box.x} ${box.y} ${box.width} ${box.height}`)
    svg.setAttribute('width', '128'); svg.setAttribute('height', '128')
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(svg))}`
  }

  dispose(): void {
    this.disposed = true
    for (const image of this.pending) { image.onload = null; image.onerror = null; image.src = '' }
    this.pending.clear(); this.entries.clear()
    this.texture.dispose()
    this.canvas.width = this.canvas.height = 0
  }
}
