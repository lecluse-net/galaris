import { prepareDocumentSnapshot } from './documentSnapshot'
import { saveBlobAsResource } from './resourceViewer'
import type { RenderedDocumentResolver } from './renderedDocument'

export async function exportDocumentBundle(
  content: string, title: string, signal: AbortSignal,
  render: (html: string, signal: AbortSignal) => Promise<Blob>,
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>,
  resolveRenderedContent?: RenderedDocumentResolver,
): Promise<void> {
  let bytes = 0
  const html = await prepareDocumentSnapshot(content, title, signal, async blob => {
    bytes += Math.ceil(blob.size / 3) * 4
    if (bytes > 12_000_000) throw new Error('Snapshot too large')
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('Image unavailable'))
      reader.onerror = () => reject(reader.error)
      reader.readAsDataURL(blob)
    })
  }, resolveImage, true, resolveRenderedContent)
  signal.throwIfAborted()
  if (new Blob([html]).size > 12_000_000) throw new Error('Snapshot too large')
  const bundle = await render(html, signal)
  signal.throwIfAborted()
  if (bundle.type !== 'application/zip') throw new Error('Invalid archive response')
  // eslint-disable-next-line no-control-regex -- Export filenames deliberately exclude ASCII control characters.
  saveBlobAsResource(bundle, (title.replace(/[\u0000-\u001f/\\:*?"<>|]/g, '-').trim().slice(0, 180) || 'document') + '.zip')
}
