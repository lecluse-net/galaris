import { GeneralHtmlSupport, StyleUtils, type Editor, type ModelElement, type StyleUtilsIsEnabledForBlockEvent } from 'ckeditor5'

export const calloutKinds = ['info', 'warning', 'question', 'error', 'stop', 'forbidden', 'search'] as const
const calloutClasses = ['galaris-callout', ...calloutKinds.map(kind => 'galaris-callout-' + kind)]

/** Native styles use CKEditor's quote container to wrap and edit several blocks together. */
export function attachCalloutStyles(editor: Editor): void {
  const styles = editor.commands.get('style')!
  const html = editor.plugins.get(GeneralHtmlSupport)
  const definitions = editor.config.get('style.definitions') ?? []
  const isCallout = (classes: string[]) => classes.includes('galaris-callout')
  editor.plugins.get(StyleUtils).on<StyleUtilsIsEnabledForBlockEvent>('isStyleEnabledForBlock', (event, [definition, block]) => {
    if (isCallout(definition.classes) && block.parent?.is('element') && editor.model.schema.checkChild(block.parent, 'blockQuote') && editor.model.schema.checkChild('blockQuote', block)) {
      event.return = true
      event.stop()
    }
  }, { priority: 'high' })

  styles.on('execute', (event, [options]: [{ styleName: string; forceValue?: boolean }]) => {
    const definition = definitions.find(item => item.name === options.styleName)
    if (!definition || !isCallout(definition.classes)) return
    event.stop()
    const remove = options.forceValue === false || options.forceValue === undefined && styles.value.includes(options.styleName)
    editor.model.change(() => {
      if (!remove) editor.execute('blockQuote', { forceValue: true })
      const containers = new Set<ModelElement>()
      for (const block of editor.model.document.selection.getSelectedBlocks()) {
        const container = block.findAncestor('blockQuote')
        if (container) containers.add(container)
      }
      for (const container of containers) {
        html.removeModelHtmlClass('blockquote', calloutClasses, container)
        if (!remove) html.addModelHtmlClass('blockquote', definition.classes, container)
      }
      if (remove) editor.execute('blockQuote', { forceValue: false })
    })
  }, { priority: 'high' })
}
