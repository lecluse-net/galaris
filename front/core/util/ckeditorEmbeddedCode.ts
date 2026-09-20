import { SourceEditing, toWidget, type Editor, type ModelElement, type ViewElement, type ViewNode } from 'ckeditor5'

export interface EmbeddedCodeTarget { key: number; element: HTMLElement; source: string; language: string }

function sourceText(node: ViewNode): string {
  if (node.is('$text')) return node.data
  if (!node.is('element')) return ''
  return node.name === 'br' ? '\n' : [...node.getChildren()].map(sourceText).join('')
}

/** Preserve an opaque code block in data while hosting a non-editable widget in the editor. */
export function attachEmbeddedCode(editor: Editor, languages: string[], label: string, publish: (targets: EmbeddedCodeTarget[]) => void): void {
  const targets = new Map<ModelElement, EmbeddedCodeTarget>()
  let sequence = 0, queued = false, destroyed = false
  const sourceEditing = editor.plugins.get(SourceEditing)
  const refresh = () => {
    if (queued || destroyed) return
    queued = true
    queueMicrotask(() => {
      queued = false
      if (destroyed) return
      for (const [model, target] of targets) {
        if (!model.root.is('rootElement') || model.root.rootName === '$graveyard' || !target.element.isConnected) targets.delete(model)
      }
      publish(sourceEditing.isSourceEditingMode ? [] : [...targets.values()])
    })
  }
  editor.model.schema.register('embeddedCode', { inheritAllFrom: '$blockObject', allowAttributes: ['source', 'language'] })
  editor.conversion.for('upcast').add(dispatcher => {
    dispatcher.on('element:pre', (event, data, api) => {
      const pre = data.viewItem
      const code = pre.getChild(0)
      if (!code?.is('element', 'code') || !api.consumable.test(pre, { name: true })) return
      const language = languages.find(language => code.hasClass('language-' + language))
      if (!language) return
      const model = api.writer.createElement('embeddedCode', { source: sourceText(code), language })
      if (!api.safeInsert(model, data.modelCursor)) return
      api.consumable.consume(pre, { name: true })
      api.consumable.consume(code, { name: true, classes: ['language-' + language] })
      api.updateConversionResult(model, data)
      event.stop()
    }, { priority: 'highest' })
  })
  editor.conversion.for('dataDowncast').elementToElement({
    model: { name: 'embeddedCode', attributes: ['source', 'language'] },
    view: (model, { writer }) => {
      const code = writer.createContainerElement('code', { class: 'language-' + String(model.getAttribute('language')) })
      writer.insert(writer.createPositionAt(code, 0), writer.createText(String(model.getAttribute('source') ?? '')))
      return writer.createContainerElement('pre', {}, [code])
    },
  })
  editor.conversion.for('editingDowncast').elementToElement({
    model: { name: 'embeddedCode', attributes: ['source', 'language'] },
    view: (model, { writer }): ViewElement => {
      const source = String(model.getAttribute('source') ?? '')
      const host = writer.createRawElement('div', { 'data-cke-ignore-events': 'true' }, element => {
        targets.set(model, { key: ++sequence, element, source, language: String(model.getAttribute('language')) })
        refresh()
      })
      return toWidget(writer.createContainerElement('div', { class: 'embedded-code-widget' }, [host]), writer, { label })
    },
  })
  editor.ui.on('update', refresh)
  sourceEditing.on('change:isSourceEditingMode', refresh)
  editor.on('destroy', () => { destroyed = true; targets.clear(); publish([]) })
}
