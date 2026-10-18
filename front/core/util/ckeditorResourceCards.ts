import { toWidget, type Editor } from 'ckeditor5'

/** Keep portable card HTML, but select, move and delete each card as one object. */
export function attachResourceCards(editor: Editor): void {
  editor.model.schema.register('resourceCard', {
    inheritAllFrom: '$blockObject',
    allowContentOf: 'blockQuote',
    allowAttributes: ['cardClasses'],
  })
  editor.conversion.for('upcast').elementToElement({
    view: { name: 'blockquote', classes: 'galaris-link-card' },
    model: (view, { writer }) => writer.createElement('resourceCard', { cardClasses: [...view.getClassNames()] }),
    converterPriority: 'high',
  })
  editor.conversion.for('dataDowncast').elementToElement({
    model: { name: 'resourceCard', attributes: ['cardClasses'] },
    view: (model, { writer }) => writer.createContainerElement('blockquote', { class: (model.getAttribute('cardClasses') as string[]).join(' ') }),
  })
  editor.conversion.for('editingDowncast').elementToElement({
    model: { name: 'resourceCard', attributes: ['cardClasses'] },
    view: (model, { writer }) => toWidget(
      writer.createContainerElement('blockquote', { class: (model.getAttribute('cardClasses') as string[]).join(' ') }), writer,
    ),
  })
}
