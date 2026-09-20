import { FileRepository, ImageUtils, type Editor, type ViewElement } from 'ckeditor5'
import { attachmentReference } from './richText'

interface AttachmentAdapter {
  resolve: (documentId: string, attachmentId: string) => Promise<Blob> | undefined
  upload: (file: File, signal: AbortSignal, progress: (value: number) => void) => Promise<string>
}
/** Storage integration only. CKEditor owns image selection, resizing, captions and drag/drop. */
export function attachDocumentImages(editor: Editor, adapter: AttachmentAdapter): void {
  const urls = new Map<string, Promise<string | undefined>>()
  const liveUrls = new Set<string>()
  const uploads = new Set<AbortController>()
  let destroyed = false
  editor.on('destroy', () => { destroyed = true; uploads.forEach(value => value.abort()); liveUrls.forEach(URL.revokeObjectURL) })
  editor.plugins.get(FileRepository).createUploadAdapter = loader => {
    const abort = new AbortController()
    uploads.add(abort)
    return {
      async upload() {
        try {
          const file = await loader.file
          if (!file) throw new Error('Missing attachment')
          loader.uploadTotal = file.size
          const uri = await adapter.upload(file, abort.signal, value => { loader.uploaded = Math.round(value * file.size) })
          return { default: uri }
        } finally { uploads.delete(abort) }
      },
      abort() { abort.abort() },
    }
  }
  const resolve = (uri: string): Promise<string | undefined> => {
    let value = urls.get(uri)
    if (value) return value
    const reference = attachmentReference(uri)
    value = Promise.resolve(reference ? adapter.resolve(...reference) : undefined).then(blob => {
      if (!blob || destroyed) { urls.delete(uri); return undefined }
      const url = URL.createObjectURL(blob)
      liveUrls.add(url)
      return url
    }).catch(() => { urls.delete(uri); return undefined })
    urls.set(uri, value)
    return value
  }
  editor.conversion.for('editingDowncast').add(dispatcher => {
    for (const type of ['imageBlock', 'imageInline']) dispatcher.on(`attribute:src:${type}`, (event, data, api) => {
      const uri = String(data.attributeNewValue ?? '')
      if (!attachmentReference(uri)) return
      const view = api.mapper.toViewElement(data.item)
      const image = view && editor.plugins.get(ImageUtils).findViewImgElement(view)
      if (!image || !api.consumable.consume(data.item, event.name)) return
      api.writer.removeAttribute('src', image)
      void resolve(uri).then(url => {
        if (!url || destroyed || data.item.getAttribute('src') !== uri) return
        editor.editing.view.change(writer => writer.setAttribute('src', url, image as ViewElement))
      })
    }, { priority: 'high' })
  })
}
