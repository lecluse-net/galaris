import { type Editor, type ModelElement, type ViewUIElement } from 'ckeditor5'
import { richLinkTarget } from './richText'
import type { ResourceEmbedTarget } from './resourceEmbed'

/** Authored cards retain only their URI/title; Vue previews live outside the data model. */
export function attachResourceEmbeds(editor: Editor, publish: (targets: ResourceEmbedTarget[]) => void): void {
  const hosts = new Map<ModelElement, { uri: string; view: ViewUIElement; target?: ResourceEmbedTarget }>()
  let sequence = 0, queued = false, disposed = false
  const refresh = (): void => {
    if (queued || disposed) return
    queued = true
    queueMicrotask(() => {
      queued = false
      if (disposed) return
      const root = editor.model.document.getRoot()
      if (!root) return
      const cards = new Map<ModelElement, { uri: string; title: string }>()
      for (const node of editor.model.createRangeIn(root).getItems()) {
        if (!node.is('element', 'resourceCard')) continue
        const classes = node.getAttribute('cardClasses') as string[]
        if (!classes.includes('galaris-process-diagram') && !classes.includes('galaris-agent-card')) continue
        for (const item of editor.model.createRangeIn(node).getItems()) {
          const uri = item.getAttribute('linkHref')
          if (typeof uri === 'string' && richLinkTarget(uri)) {
            cards.set(node, { uri, title: item.is('$textProxy') ? item.data : '' }); break
          }
        }
      }
      if (cards.size === hosts.size && [...cards].every(([model, card]) => hosts.get(model)?.uri === card.uri && hosts.get(model)?.view.parent)) return
      editor.editing.view.change(writer => {
        for (const [model, host] of hosts) {
          if (cards.get(model)?.uri === host.uri && host.view.parent) continue
          if (host.view.parent) writer.remove(host.view)
          hosts.delete(model)
        }
        for (const [model, card] of cards) {
          if (hosts.has(model)) continue
          const view = editor.editing.mapper.toViewElement(model)
          if (!view) continue
          const host: { uri: string; view: ViewUIElement; target?: ResourceEmbedTarget } = {
            uri: card.uri,
            view: writer.createUIElement('div', { class: 'galaris-resource-embed', 'data-cke-ignore-events': 'true' }, function (document) {
              if (host.target) return host.target.element
              const element = this.toDomElement(document)
              host.target = { key: ++sequence, element, ...card }
              queueMicrotask(() => { if (!disposed) publish([...hosts.values()].flatMap(value => value.target ? [value.target] : [])) })
              return element
            }),
          }
          hosts.set(model, host)
          writer.insert(writer.createPositionAt(view, 'end'), host.view)
        }
      })
      publish([...hosts.values()].flatMap(value => value.target ? [value.target] : []))
    })
  }
  editor.ui.on('update', refresh)
  editor.on('destroy', () => { disposed = true; hosts.clear(); publish([]) })
}
