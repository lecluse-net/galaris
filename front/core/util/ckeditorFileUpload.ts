import { FileDialogButtonView, IconImportExport, ModelLivePosition, type Editor, type ModelPosition } from 'ckeditor5'
import { documentResourceHtml } from './documentResources'

export interface DocumentUploadProgress { name: string; index: number; total: number; progress: number }

/** Upload through the document's attachment service, then insert at a live model position. */
export function attachDocumentFileUpload(editor: Editor, options: {
  upload?: (file: File, signal: AbortSignal, progress: (value: number) => void) => Promise<string>
  translate: (key: string) => string
  progress: (value: DocumentUploadProgress | null) => void
  failed: (name: string) => void
}): () => void {
  let request: AbortController | undefined
  let destroyed = false
  let button: FileDialogButtonView | undefined
  const enabled = (): boolean => Boolean(options.upload) && !editor.isReadOnly && !request
  const refresh = (): void => { if (button) button.isEnabled = enabled() }
  const cancel = (): void => { request?.abort() }
  const upload = async (files: File[], start: ModelPosition): Promise<void> => {
    if (!enabled() || !files.length || !options.upload) return
    const controller = new AbortController()
    request = controller
    let position = ModelLivePosition.fromPosition(start, 'toNext')
    refresh()
    editor.editing.view.focus()
    try {
      for (const [index, file] of files.entries()) {
        if (controller.signal.aborted || destroyed || editor.isReadOnly || position.root.rootName === '$graveyard') break
        const report = (progress: number): void => {
          if (!controller.signal.aborted && !destroyed) options.progress({ name: file.name, index: index + 1, total: files.length, progress })
        }
        report(0)
        try {
          const uri = await options.upload(file, controller.signal, report)
          if (controller.signal.aborted || destroyed || editor.isReadOnly || position.root.rootName === '$graveyard') break
          const html = documentResourceHtml({ uri, name: file.name, size: file.size, mediaType: file.type })
          const fragment = editor.data.toModel(editor.data.processor.toView(html))
          const selection = editor.model.createSelection(position)
          editor.model.insertContent(fragment, selection)
          const next = selection.getLastPosition()
          if (next) {
            position.detach()
            position = ModelLivePosition.fromPosition(next, 'toNext')
          }
        } catch {
          if (!controller.signal.aborted && !destroyed) options.failed(file.name)
        }
      }
    } finally {
      position.detach()
      request = undefined
      if (!destroyed) { options.progress(null); refresh() }
    }
  }
  editor.ui.componentFactory.add('documentUploadFile', locale => {
    button = new FileDialogButtonView(locale)
    button.set({ allowMultipleFiles: true, acceptedType: '*', label: options.translate('richEditor.resources.uploadFile'), icon: IconImportExport, tooltip: true })
    button.on('done', (_event, files: FileList) => {
      const position = editor.model.document.selection.getFirstPosition()
      if (position) void upload(Array.from(files), position)
    })
    refresh()
    return button
  })
  editor.editing.view.document.on('clipboardInput', (event, data) => {
    const files = Array.from(data.dataTransfer.files).filter((file): file is File => file instanceof File)
    if (!files.length || !options.upload) return
    // Keep CKEditor's native image upload, selection and drag/drop for image-only transfers.
    if (files.every(file => /^image\/(png|jpeg|webp|gif)$/.test(file.type))) return
    event.stop()
    if (!enabled()) return
    const range = data.targetRanges?.[0]
    const position = range ? editor.editing.mapper.toModelRange(range).start : editor.model.document.selection.getFirstPosition()
    if (position) void upload(files, position)
  }, { priority: 'highest' })
  editor.on('change:isReadOnly', () => { if (editor.isReadOnly) cancel(); refresh() })
  editor.data.on('set', cancel, { priority: 'highest' })
  editor.on('destroy', () => { destroyed = true; cancel(); options.progress(null) })
  return cancel
}
