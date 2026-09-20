import { GeneralHtmlSupport, type Editor, type ModelElement, type ViewUIElement } from 'ckeditor5'
import { createDocumentPlayer, documentPlayer, type DocumentMediaResolver, type DocumentPlayer, type PdfPreviewSource } from './documentMedia'
import type { DocumentResource } from './documentResources'

/** Players live in CKEditor UI elements; the saved card keeps its portable thumbnail. */
export function attachDocumentPlayers(editor: Editor, resolve: DocumentMediaResolver, resources: () => DocumentResource[], translate: (key: string) => string, openPdf: (source: PdfPreviewSource) => void): void {
  const attribute = editor.plugins.get(GeneralHtmlSupport).getGhsAttributeNameForElement('blockquote')
  const players = new Map<ModelElement, { src: string; kind: string; view: ViewUIElement; dispose: () => void }>()
  editor.ui.on('update', () => {
    const root = editor.model.document.getRoot()
    if (!root) return
    const cards = new Map<ModelElement, DocumentPlayer>()
    for (const node of editor.model.createRangeIn(root).getItems()) {
      if (!node.is('element', 'blockQuote')) continue
      const classes = (node.getAttribute(attribute) as { classes?: string[] } | undefined)?.classes ?? []
      if (!classes.includes('galaris-link-card')) continue
      for (const item of editor.model.createRangeIn(node).getItems()) {
        const href = item.getAttribute('linkHref')
        if (typeof href !== 'string') continue
        const resource = resources().find(value => value.uri === href)
        const title = resource?.name ?? (item.is('$textProxy') ? item.data : '')
        const target = documentPlayer(href, title, classes, resource?.mediaType)
        if (target) { cards.set(node, target); break }
      }
    }
    if (cards.size === players.size && [...cards].every(([card, target]) => players.get(card)?.src === target.src && players.get(card)?.kind === target.kind && players.get(card)?.view.parent)) return
    editor.editing.view.change(writer => {
      for (const [card, player] of players) {
        if (cards.get(card)?.src === player.src && cards.get(card)?.kind === player.kind && player.view.parent) continue
        player.dispose()
        if (player.view.parent) writer.remove(player.view)
        const view = editor.editing.mapper.toViewElement(card)
        if (view) writer.removeClass('galaris-youtube-card', view)
        players.delete(card)
      }
      for (const [card, target] of cards) {
        if (players.has(card)) continue
        const view = editor.editing.mapper.toViewElement(card)
        if (!view) continue
        let dispose = () => {}
        let element: HTMLElement | undefined
        const player = writer.createUIElement('div', {}, function (document) {
          if (element) return element
          element = this.toDomElement(document)
          const media = createDocumentPlayer(document, target, resolve, translate, openPdf)
          dispose = media.dispose
          element.append(media.element)
          return element
        })
        players.set(card, { src: target.src, kind: target.kind, view: player, dispose: () => dispose() })
        if (target.kind === 'youtube') writer.addClass('galaris-youtube-card', view)
        writer.insert(writer.createPositionAt(view, 'end'), player)
      }
    })
  })
  editor.on('destroy', () => { players.forEach(player => player.dispose()); players.clear() })
}
