import { ButtonView, ContextualBalloon, GeneralHtmlSupport, IconBoxWithMarker, IconLink, ModelLiveRange, ToolbarView, findAttributeRange, type Editor, type ModelElement, type ModelRange } from 'ckeditor5'
import { sanitizeRichHtml, validRichLink } from './richText'

interface LinkTarget { url: string; range: ModelRange; card?: ModelElement }

/** Extend native link/image balloons; cards also expose their action from the description. */
export function attachLinkCards(editor: Editor, createCard: (url: string) => Promise<string>, translate: (key: string) => string, failed: () => void): void {
  const balloon = editor.plugins.get(ContextualBalloon)
  const buttons = new Set<ButtonView>()
  const savedCards = new Map<string, string>()
  const cardAttribute = editor.plugins.get(GeneralHtmlSupport).getGhsAttributeNameForElement('blockquote')
  let busy = false, destroyed = false
  const target = (): LinkTarget | undefined => {
    const selection = editor.model.document.selection
    const position = selection.getFirstPosition()
    if (!position) return
    const card = position.getAncestors().find(node => node.is('element', 'blockQuote')
      && (node.getAttribute(cardAttribute) as { classes?: string[] } | undefined)?.classes?.includes('galaris-link-card'))
    if (card?.is('element')) {
      for (const node of editor.model.createRangeIn(card).getItems()) {
        const href = node.getAttribute('linkHref')
        if (typeof href === 'string' && /^https?:\/\//i.test(href) && validRichLink(href)) {
          return { url: href, range: editor.model.createRangeOn(card), card }
        }
      }
    }
    const href = selection.getSelectedElement()?.getAttribute('linkHref') ?? selection.getAttribute('linkHref')
    if (typeof href === 'string' && /^https:\/\//i.test(href) && validRichLink(href)) {
      return { url: href, range: findAttributeRange(position, 'linkHref', href, editor.model) }
    }
  }
  const updateButtons = (): void => {
    const selected = target()
    for (const button of buttons) button.set({
      label: translate(selected?.card ? 'richEditor.resources.asUrl' : 'richEditor.resources.asCard'),
      icon: selected?.card ? IconLink : IconBoxWithMarker,
      isEnabled: !busy && !editor.isReadOnly && Boolean(selected),
      isVisible: !busy && !editor.isReadOnly && Boolean(selected),
    })
  }
  const convert = async (): Promise<void> => {
    const selected = target()
    if (!selected || busy || editor.isReadOnly) return
    const live = ModelLiveRange.fromRange(selected.range)
    const content = (): string => editor.data.stringify(editor.model.getSelectedContent(editor.model.createSelection(live)))
    const original = content()
    busy = true; updateButtons()
    try {
      let html: string
      if (selected.card) {
        // Preserve the existing thumbnail and authored text across appearance
        // changes, instead of fetching the page and duplicating its attachment.
        if (original.includes('<img ')) savedCards.set(selected.url, original)
        const link = document.createElement('a'); link.href = selected.url; link.textContent = selected.url
        html = '<p>' + link.outerHTML + '</p>'
      } else html = savedCards.get(selected.url) ?? await createCard(selected.url)
      if (destroyed || editor.isReadOnly || live.root.rootName === '$graveyard' || live.isCollapsed || content() !== original) return
      editor.model.change(writer => {
        writer.setSelection(live)
        const fragment = editor.data.toModel(editor.data.processor.toView(sanitizeRichHtml(html, 'document')))
        editor.model.insertContent(fragment)
      })
      editor.editing.view.focus()
    } catch { if (!destroyed) failed() }
    finally { live.detach(); busy = false; if (!destroyed) updateButtons() }
  }
  editor.ui.componentFactory.add('documentLinkAppearance', locale => {
    const button = new ButtonView(locale)
    button.set({ withText: false, tooltip: true })
    buttons.add(button); updateButtons()
    button.on('execute', () => { void convert() })
    return button
  })
  const toolbar = new ToolbarView(editor.locale)
  toolbar.fillFromConfig(['documentLinkAppearance'], editor.ui.componentFactory)
  toolbar.class = 'galaris-link-card-toolbar'
  const hide = (): void => { if (balloon.hasView(toolbar)) balloon.remove(toolbar) }
  const refresh = (): void => {
    updateButtons()
    const selected = target()
    const selectedImage = editor.model.document.selection.getSelectedElement()?.name.startsWith('image')
    if (!selected?.card || editor.isReadOnly || selectedImage || editor.commands.get('link')?.value) { hide(); return }
    const view = editor.editing.mapper.toViewElement(selected.card)
    const element = view && editor.editing.view.domConverter.mapViewToDom(view)
    if (!element) return
    if (!balloon.hasView(toolbar)) balloon.add({ view: toolbar, position: { target: element } })
    else balloon.updatePosition({ target: element })
  }
  toolbar.keystrokes.set('Esc', (_data, cancel) => { hide(); editor.editing.view.focus(); cancel() })
  editor.ui.addToolbar(toolbar, { isContextual: true })
  // The UI update runs after commands and the editing view have caught up with the
  // model. Selection events run too early and can leave the action disabled.
  editor.ui.on('update', refresh)
  editor.on('change:isReadOnly', refresh)
  editor.on('destroy', () => { destroyed = true; hide(); toolbar.destroy(); buttons.clear() })
}
