export function mountImageResize(
  dom: HTMLElement, canResize: () => boolean, getImage: () => HTMLImageElement | null,
  commit: (width: string) => void, pixels: boolean, frame?: HTMLElement,
): () => void {
  const handle = document.createElement('span')
  handle.className = 'galaris-image-resize'; handle.setAttribute('aria-hidden', 'true'); dom.append(handle)
  const controller = new AbortController()
  handle.addEventListener('pointerdown', event => {
    const image = getImage()
    if (event.button !== 0 || !canResize() || !image?.naturalWidth) return
    event.preventDefault(); event.stopPropagation(); handle.setPointerCapture(event.pointerId)
    const start = event.clientX, bounds = image.getBoundingClientRect()
    const scale = bounds.width / (image.offsetWidth || bounds.width) || 1
    const width = bounds.width / scale
    const original = [dom.style.width, image.style.width, image.style.height, frame?.style.width] as const
    let available = 1600
    if (!pixels) {
      // Percentages are relative to the image's own containing block, including in table cells.
      dom.style.width = '100%'
      available = dom.getBoundingClientRect().width / scale || 1600
      dom.style.width = original[0]
    }
    let moved = false
    const gesture = new AbortController()
    const options = { signal: gesture.signal }
    const restore = () => {
      dom.style.width = original[0]; image.style.width = original[1]; image.style.height = original[2]
      if (frame) frame.style.width = original[3] ?? ''
    }
    const cancel = () => { gesture.abort(); restore() }
    const move = (next: PointerEvent) => {
      if (next.pointerId !== event.pointerId) return
      moved = true
      dom.style.width = `${Math.min(available, Math.max(32, width + (next.clientX - start) / scale))}px`
      if (frame) frame.style.width = '100%'
      image.style.width = '100%'; image.style.height = 'auto'
    }
    const end = (next: PointerEvent) => {
      if (next.pointerId !== event.pointerId) return
      gesture.abort()
      controller.signal.removeEventListener('abort', cancel)
      if (!moved || next.type !== 'pointerup' || !canResize()) { restore(); return }
      const resized = image.getBoundingClientRect().width / scale
      commit(pixels ? `${Math.max(1, Math.round(resized))}px` : `${Math.min(100, resized / available * 100)}%`)
    }
    handle.addEventListener('pointermove', move, options)
    handle.addEventListener('pointerup', end, options)
    handle.addEventListener('pointercancel', end, options)
    handle.addEventListener('lostpointercapture', end, options)
    controller.signal.addEventListener('abort', cancel, { once: true })
  }, { signal: controller.signal })
  return () => { controller.abort(); handle.remove() }
}
