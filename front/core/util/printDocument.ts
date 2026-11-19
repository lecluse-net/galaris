import { prepareDocumentSnapshot } from './documentSnapshot'
import type { RenderedDocumentResolver } from './renderedDocument'

/** Print a static snapshot; document scripts never run in the application origin. */
export async function printDocument(
  content: string,
  title: string,
  signal: AbortSignal,
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>,
  resolveRenderedContent?: RenderedDocumentResolver,
): Promise<void> {
  await printStaticDocument(title, signal, imageUrl =>
    prepareDocumentSnapshot(content, title, signal, imageUrl, resolveImage, false, resolveRenderedContent))
}

/** Open the browser print dialog with a prepared, self-contained snapshot. */
export async function printStaticDocument(
  title: string,
  signal: AbortSignal,
  prepare: (imageUrl: (blob: Blob) => Promise<string>) => Promise<string>,
): Promise<void> {
  const frame = document.createElement('iframe')
  const urls: string[] = []
  let disposed = false
  const cleanup = () => {
    disposed = true
    frame.remove()
    urls.forEach(URL.revokeObjectURL)
    signal.removeEventListener('abort', cleanup)
  }
  signal.addEventListener('abort', cleanup, { once: true })
  try {
    signal.throwIfAborted()
    const html = await prepare(async blob => {
      if (disposed) throw new Error('Print preparation cancelled')
      const url = URL.createObjectURL(blob)
      urls.push(url)
      return url
    })
    signal.throwIfAborted()
    frame.title = title
    frame.setAttribute('aria-hidden', 'true')
    frame.tabIndex = -1
    frame.className = 'document-print-frame'
    frame.style.cssText = 'position:fixed;left:-10000px;top:0;width:190mm;height:277mm;border:0'
    frame.sandbox.add('allow-same-origin', 'allow-modals')
    frame.srcdoc = html
    await new Promise<void>((resolve, reject) => {
      const abort = () => reject(signal.reason)
      signal.addEventListener('abort', abort, { once: true })
      frame.addEventListener('load', () => {
        signal.removeEventListener('abort', abort)
        resolve()
      }, { once: true })
      document.body.appendChild(frame)
    })
    signal.throwIfAborted()
    const target = frame.contentWindow
    const printed = frame.contentDocument
    if (!target || !printed) throw new Error('Print frame unavailable')
    await Promise.all([...printed.images].map(image => image.decode()))
    await printed.fonts.ready
    signal.throwIfAborted()
    await new Promise<void>((resolve, reject) => {
      const lifetime = new AbortController()
      const aborted = () => { lifetime.abort(); cleanup(); reject(signal.reason) }
      const finished = () => { lifetime.abort(); cleanup(); resolve() }
      signal.addEventListener('abort', aborted, { once: true, signal: lifetime.signal })
      target.addEventListener('afterprint', finished, { once: true, signal: lifetime.signal })
      // Some WebKit versions suppress events from a frame with scripting disabled.
      // Interaction in the application also signals a return from its print dialog.
      const options = { capture: true, once: true, signal: lifetime.signal }
      window.addEventListener('pointerdown', finished, options)
      window.addEventListener('keydown', finished, options)
      try {
        target.focus()
        target.print()
      } catch (error) {
        lifetime.abort()
        reject(error)
      }
    })
  } catch (error) {
    cleanup()
    throw error
  }
}
