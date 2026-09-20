import { preparePortableDocumentSnapshot } from './documentSnapshot'
import { saveBlobAsResource } from './resourceViewer'
import type { RenderedDocumentResolver } from './renderedDocument'

export async function exportDocumentPdf(
  ...args: Parameters<typeof createDocumentPdf>
): Promise<void> {
  const file = await createDocumentPdf(...args)
  saveBlobAsResource(file, file.name)
}

export async function createDocumentPdf(
  content: string,
  title: string,
  signal: AbortSignal,
  render: (html: string, signal: AbortSignal) => Promise<Blob>,
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>,
  resolveRenderedContent?: RenderedDocumentResolver,
): Promise<File> {
  const html = await preparePortableDocumentSnapshot(content, title, signal, resolveImage, resolveRenderedContent)
  const pdf = await render(html, signal)
  signal.throwIfAborted()
  if (pdf.type !== 'application/pdf' || await pdf.slice(0, 5).text() !== '%PDF-') throw new Error('Invalid PDF response')
  signal.throwIfAborted()
  // eslint-disable-next-line no-control-regex -- Export filenames deliberately exclude ASCII control characters.
  const name = title.replace(/[\u0000-\u001f/\\:*?"<>|]/g, '-').trim().replace(/\.pdf$/i, '').slice(0, 180) || 'document'
  return new File([pdf], name + '.pdf', { type: 'application/pdf' })
}
