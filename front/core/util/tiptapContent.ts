import { Extension, Node, mergeAttributes, type Editor, type Extensions } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import { TextStyleKit } from '@tiptap/extension-text-style'
import TextAlign from '@tiptap/extension-text-align'
import Highlight from '@tiptap/extension-highlight'
import Subscript from '@tiptap/extension-subscript'
import Superscript from '@tiptap/extension-superscript'
import Link from '@tiptap/extension-link'
import { Table, TableKit } from '@tiptap/extension-table'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { codeLanguageLabel, codeTokens } from './codeHighlight'
import { EditorialTableView } from './editorialTableView'
import { attachmentReference, richLinkHref, sanitizeRichHtml, type ContentProfile } from './richText'
import { documentIdFromResourceUri, documentUriFromLink } from './documentResource'
import { Checklist, ChecklistItem } from './editorialChecklist'
import { mathNode } from './editorialMath'

export type EditorToolbarGroupName = 'reading' | 'editing' | 'text' | 'paragraph' | 'insert'
export const calloutKinds = ['info', 'warning', 'question', 'error', 'stop', 'forbidden', 'search'] as const
export interface EditorObject { key: number; element: HTMLElement; source: string; language: string }
export interface ObjectHost { html: string; element: HTMLElement }
export interface ContentAdapters {
  profile: ContentProfile
  object: (target: EditorObject, mounted: boolean) => void
  card: (target: ObjectHost) => () => void
  image: (uri: string, image: HTMLImageElement) => () => void
  openImage: (uri: string) => void
  readonly: () => boolean
  codeCopy: (element: HTMLElement, source: () => string) => () => void
  linkIcon?: (element: HTMLElement, documentId: string) => () => void
  editMath?: (position: number) => void
}
let sequence = 0

/** The saved HTML is independent of the editing DOM, its players and Blob URLs. */
const RawObject = (adapters: ContentAdapters) => Node.create({
  name: 'rawObject', group: 'block', atom: true, draggable: true, selectable: true, priority: 1100,
  addAttributes: () => ({ source: { default: '' }, language: { default: 'galaris-raw-html' } }),
  parseHTML: () => [{ tag: 'pre', getAttrs: element => {
    const code = element.firstElementChild
    const language = code?.classList.contains('language-galaris-raw-html') ? 'galaris-raw-html'
      : code?.classList.contains('language-galaris-app') ? 'galaris-app' : null
    return language ? { source: code!.textContent ?? '', language } : false
  } }],
  renderHTML: ({ node }) => ['pre', {}, ['code', { class: 'language-' + node.attrs.language }, node.attrs.source]],
  addNodeView: () => ({ node, editor, getPos }) => {
    let disposed = false
    const dom = document.createElement('div'), host = document.createElement('div')
    dom.className = 'embedded-code-widget'; dom.contentEditable = 'false'; dom.append(host)
    host.contentEditable = 'false'
    const controller = new AbortController()
    const select = () => {
      if (disposed || editor.isDestroyed || !editor.isEditable) return
      const position = getPos()
      if (position !== undefined) editor.commands.setNodeSelection(position)
    }
    // Selecting the outer block must keep focus and input inside the isolated form.
    dom.addEventListener('pointerdown', select, { signal: controller.signal })
    dom.addEventListener('focusin', select, { signal: controller.signal })
    window.addEventListener('blur', () => queueMicrotask(() => {
      if (dom.contains(document.activeElement)) select()
    }), { signal: controller.signal })
    const target = { key: ++sequence, element: host, source: String(node.attrs.source), language: String(node.attrs.language) }
    queueMicrotask(() => { if (!disposed) adapters.object(target, true) })
    return { dom, stopEvent: event => dom.contains(event.target as globalThis.Node), ignoreMutation: () => true,
      destroy: () => { disposed = true; controller.abort(); adapters.object(target, false) } }
  },
})

const ResourceCard = (adapters: ContentAdapters) => Node.create({
  name: 'resourceCard', group: 'block', atom: true, draggable: true, priority: 1200,
  addAttributes: () => ({ html: { default: '' } }),
  parseHTML: () => [{ tag: 'blockquote.galaris-link-card', getAttrs: element => ({ html: element.outerHTML }) }],
  renderHTML: ({ node }) => new DOMParser().parseFromString(node.attrs.html, 'text/html').body.firstElementChild as HTMLElement,
  addNodeView: () => ({ node, editor, getPos }) => {
    const dom = new DOMParser().parseFromString(node.attrs.html, 'text/html').body.firstElementChild as HTMLElement
    dom.contentEditable = 'false'
    const dispose = adapters.card({ html: node.attrs.html, element: dom })
    const select = (event: MouseEvent) => {
      if (!editor.isEditable) return
      if (event.target instanceof Element && event.target.closest('.galaris-resource-embed, [data-document-player]')) return
      const position = getPos()
      if (position !== undefined) { editor.commands.setNodeSelection(position); editor.view.focus() }
    }
    dom.addEventListener('click', select)
    return { dom, ignoreMutation: () => true,
      stopEvent: event => event.target instanceof Element && Boolean(event.target.closest('.galaris-resource-embed, [data-document-player]')),
      destroy: () => { dom.removeEventListener('click', select); dispose() } }
  },
})

const DocumentImage = (adapters: ContentAdapters, inline: boolean) => Node.create({
  name: inline ? 'inlineImage' : 'documentImage', group: inline ? 'inline' : 'block', inline, atom: true, draggable: true,
  priority: 1050,
  addAttributes: () => ({ html: { default: '' }, src: { default: '' } }),
  parseHTML: () => (inline ? ['span.image-inline', 'img'] : ['figure.image']).map(tag => ({ tag, getAttrs: (element: HTMLElement) => {
    const image = element instanceof HTMLImageElement ? element : element.querySelector('img')
    const src = image?.getAttribute('src') ?? ''
    return attachmentReference(src) ? { html: element.outerHTML, src } : false
  } })),
  renderHTML: ({ node }) => new DOMParser().parseFromString(node.attrs.html, 'text/html').body.firstElementChild as HTMLElement,
  addNodeView: () => ({ node, editor, getPos }) => {
    const authored = new DOMParser().parseFromString(node.attrs.html, 'text/html').body.firstElementChild as HTMLElement
    const dom = document.createElement(inline ? 'span' : 'div')
    dom.classList.add('galaris-image-object'); dom.contentEditable = 'false'
    if (inline) dom.style.display = 'inline-block'
    const layoutClasses = [...authored.classList].filter(value => value.startsWith('image-style-'))
    dom.classList.add(...layoutClasses); authored.classList.remove(...layoutClasses)
    for (const property of ['float', 'margin-left', 'margin-right']) {
      const value = authored.style.getPropertyValue(property)
      if (value) { dom.style.setProperty(property, value); authored.style.removeProperty(property) }
    }
    if (authored.style.width) { dom.style.width = authored.style.width; authored.style.width = '100%' }
    const image = authored instanceof HTMLImageElement ? authored : authored.querySelector('img')!
    image.removeAttribute('src'); dom.append(authored)
    const dispose = adapters.image(String(node.attrs.src), image)
    const handle = document.createElement('span'); handle.className = 'galaris-image-resize'; handle.setAttribute('aria-hidden', 'true'); dom.append(handle)
    const controller = new AbortController()
    dom.addEventListener('click', event => {
      if (!(event instanceof MouseEvent)) return
      if (!editor.isEditable) {
        event.preventDefault(); event.stopPropagation(); adapters.openImage(String(node.attrs.src)); return
      }
      if (event.ctrlKey || event.metaKey) return
      const position = getPos()
      if (position === undefined) return
      event.preventDefault(); event.stopPropagation()
      editor.commands.setNodeSelection(position); editor.view.focus()
    }, { signal: controller.signal })
    handle.addEventListener('pointerdown', event => {
      if (!editor.isEditable) return
      event.preventDefault(); handle.setPointerCapture(event.pointerId)
      const start = event.clientX, width = image.getBoundingClientRect().width
      // Resolve 100% in this image's containing block, excluding page/cell padding.
      // Inline links and table cells need their own basis, not the editor's outer width.
      const originalWidth = dom.style.width
      dom.style.width = '100%'
      const available = dom.getBoundingClientRect().width
      dom.style.width = originalWidth
      const move = (next: PointerEvent) => { dom.style.width = Math.min(available || Infinity, Math.max(32, width + next.clientX - start)) + 'px'; authored.style.width = '100%'; image.style.width = '100%' }
      const end = () => {
        handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', end); handle.removeEventListener('pointercancel', end)
        const pos = getPos()
        if (pos === undefined || !editor.isEditable) return
        const copy = new DOMParser().parseFromString(node.attrs.html, 'text/html').body.firstElementChild as HTMLElement
        copy.style.width = available > 0 ? Math.min(100, image.getBoundingClientRect().width / available * 100) + '%' : authored.style.width
        if (!inline) copy.classList.add('image_resized')
        const img = copy instanceof HTMLImageElement ? copy : copy.querySelector('img')!
        img.src = String(node.attrs.src)
        // For a bare inline <img>, the image itself owns the saved percentage.
        if (img !== copy) img.style.width = '100%'
        editor.commands.command(({ tr }) => { tr.setNodeMarkup(pos, undefined, { ...node.attrs, html: copy.outerHTML }); return true })
      }
      handle.addEventListener('pointermove', move, { signal: controller.signal }); handle.addEventListener('pointerup', end, { once: true, signal: controller.signal }); handle.addEventListener('pointercancel', end, { once: true, signal: controller.signal })
    }, { signal: controller.signal })
    return { dom, ignoreMutation: () => true,
      destroy: () => { controller.abort(); dispose() } }
  },
})

const CodeBlock = Node.create({
  name: 'codeBlock', group: 'block', content: 'text*', marks: '', code: true, defining: true,
  addAttributes: () => ({ language: { default: 'plaintext' }, lines: { default: true }, nowrap: { default: false } }),
  parseHTML: () => [{ tag: 'pre', preserveWhitespace: 'full', getAttrs: element => {
    const code = element.querySelector('code')
    return { language: [...(code?.classList ?? [])].find(name => name.startsWith('language-'))?.slice(9) ?? 'plaintext', lines: code?.getAttribute('data-code-lines') === 'true', nowrap: code?.getAttribute('data-code-nowrap') === 'true' }
  } }],
  renderHTML: ({ node }) => ['pre', {}, ['code', { class: 'language-' + node.attrs.language,
    ...(node.attrs.lines ? { 'data-code-lines': 'true' } : {}), ...(node.attrs.nowrap ? { 'data-code-nowrap': 'true' } : {}) }, 0]],
  addKeyboardShortcuts() { return {
    'Mod-Alt-c': () => this.editor.commands.toggleNode('codeBlock', 'paragraph'),
    Tab: () => this.editor.isActive('codeBlock') && this.editor.commands.insertContent({ type: 'text', text: '\t' }),
    'Shift-Tab': () => {
      if (!this.editor.isActive('codeBlock')) return false
      return this.editor.commands.command(({ tr, state }) => {
        const { $from } = state.selection, prefix = $from.parent.textContent.slice(0, $from.parentOffset)
        const line = prefix.lastIndexOf('\n') + 1, spaces = /^\t|^ {1,4}/.exec(prefix.slice(line))?.[0]
        if (spaces) tr.delete($from.start() + line, $from.start() + line + spaces.length)
        return true
      })
    },
  } },
})

const HtmlAttributes = (adapters: ContentAdapters) => Extension.create({
  name: 'editorialAttributes',
  addGlobalAttributes: () => [{ types: ['paragraph', 'heading', 'blockquote', 'bulletList', 'orderedList', 'listItem', 'table', 'tableRow', 'tableCell', 'tableHeader', 'tableFigure', 'caption'], attributes: {
    editorialClass: { default: null, parseHTML: element => element.getAttribute('class'), renderHTML: attrs => attrs.editorialClass ? { class: attrs.editorialClass } : {} },
    editorialStyle: { default: null, parseHTML: element => element.getAttribute('style'), renderHTML: attrs => attrs.editorialStyle ? { style: attrs.editorialStyle } : {} },
    reversed: { default: false, parseHTML: element => element.hasAttribute('reversed'), renderHTML: attrs => attrs.reversed ? { reversed: '' } : {} },
    value: { default: null, parseHTML: element => element.getAttribute('value'), renderHTML: attrs => attrs.value ? { value: attrs.value } : {} },
  } }],
  addProseMirrorPlugins() { return [new Plugin({ key: new PluginKey('galarisCodeSyntax'), props: {
    decorations: state => {
      const decorations: Decoration[] = []
      state.doc.descendants((node, pos) => {
        if (node.type.name !== 'codeBlock') return
        decorations.push(Decoration.node(pos, pos + node.nodeSize, { 'data-code-language': codeLanguageLabel(node.attrs.language) }))
        if (adapters.profile === 'document' && adapters.readonly()) {
          let dispose: (() => void) | undefined
          decorations.push(Decoration.widget(pos + 1, (view, getPos) => {
            const element = document.createElement('span')
            element.className = 'galaris-code-actions'
            dispose = adapters.codeCopy(element, () => {
              const position = getPos()
              return position === undefined ? '' : view.state.doc.nodeAt(position - 1)?.textContent ?? ''
            })
            return element
          }, { side: -1, key: 'code-copy-' + pos, stopEvent: () => true, ignoreSelection: true, destroy: () => dispose?.() }))
        }
        for (const token of codeTokens(node.textContent, node.attrs.language)) decorations.push(Decoration.inline(pos + 1 + token.start, pos + 1 + token.end, { class: token.className }))
        if (node.attrs.lines) {
          let offset = 0
          node.textContent.split('\n').forEach((line, index) => {
            decorations.push(Decoration.widget(pos + 1 + offset, () => {
              const span = document.createElement('span'); span.className = 'galaris-code-line'; span.dataset.codeLine = String(index + 1); span.setAttribute('aria-hidden', 'true'); return span
            }, { side: -1 })); offset += line.length + 1
          })
        }
      })
      return DecorationSet.create(state.doc, decorations)
    },
  } })] },
})

export function contentExtensions(adapters: ContentAdapters): Extensions {
  return [Node.create({ name: 'paragraph', priority: 2000, group: 'block', content: 'inline*', parseHTML: () => [{ tag: 'p' }], renderHTML: ({ HTMLAttributes }) => ['p', HTMLAttributes, 0], addCommands() { return { setParagraph: () => ({ commands }) => commands.setNode(this.name) } } }),
    StarterKit.extend({
      addExtensions() {
        return (this.parent?.() ?? []).map(extension => adapters.profile === 'document' && extension.name === 'strike'
          ? extension.extend({ addKeyboardShortcuts: () => ({}) }) : extension)
      },
    }).configure({ paragraph: false, codeBlock: false, link: false, trailingNode: false }), Link.extend({
    addAttributes() { return {
      ...this.parent?.(),
      href: { default: null, parseHTML: element => element.getAttribute('data-rich-reference') ?? element.getAttribute('href') },
      title: { default: null, parseHTML: element => element.getAttribute('title'), renderHTML: attrs => ({ title: /^https?:\/\//i.test(attrs.href ?? '') ? attrs.href : attrs.title }) },
    } },
    renderHTML({ HTMLAttributes }) { const uri = String(HTMLAttributes.href ?? ''); return ['a', mergeAttributes(HTMLAttributes, { href: richLinkHref(uri) ?? uri, 'data-rich-reference': uri, target: '_blank', rel: 'noopener noreferrer' }), 0] },
    addMarkView() { return ({ HTMLAttributes }) => {
      const dom = document.createElement('a'), uri = String(HTMLAttributes.href ?? '')
      for (const [key, value] of Object.entries(mergeAttributes(HTMLAttributes, { href: richLinkHref(uri) ?? uri, 'data-rich-reference': uri, target: '_blank', rel: 'noopener noreferrer' }))) {
        if (value !== null && value !== undefined) dom.setAttribute(key, String(value))
      }
      const documentUri = documentUriFromLink(uri, window.location.origin)
      const id = documentUri && documentIdFromResourceUri(documentUri)
      if (!id || !adapters.linkIcon) return { dom }
      const icon = document.createElement('span'), contentDOM = document.createElement('span')
      icon.className = 'document-link-icon'; icon.contentEditable = 'false'; icon.setAttribute('aria-hidden', 'true')
      dom.append(icon, contentDOM)
      const dispose = adapters.linkIcon(icon, id)
      return { dom, contentDOM, ignoreMutation: mutation => mutation.type !== 'selection' && icon.contains(mutation.target), destroy: dispose }
    } },
  }).configure({ openOnClick: false, autolink: false, protocols: ['document', 'memory', 'data', 'galaris'] }), TextStyleKit, TextAlign.extend({
    addKeyboardShortcuts() { return adapters.profile === 'document' ? {} : this.parent?.() ?? {} },
  }).configure({ types: ['heading', 'paragraph'] }), Highlight.extend({
    addAttributes() { return { ...this.parent?.(), editorialClass: { default: null, parseHTML: element => element.getAttribute('class'), renderHTML: attrs => attrs.editorialClass ? { class: attrs.editorialClass } : {} } } },
  }).configure({ multicolor: true }), Subscript, Superscript,
  TableKit.configure({ table: false }), Table.extend({
    // TableView's editing-only min-width is outside the portable HTML contract.
    // Serialize authored styles and column widths, never the editor's layout hints.
    renderHTML({ node, HTMLAttributes }) {
      const widths: Array<number | null> = []
      node.firstChild?.forEach(cell => {
        const values = cell.attrs.colwidth as number[] | null
        for (let i = 0; i < Number(cell.attrs.colspan ?? 1); i++) widths.push(values?.[i] ?? null)
      })
      const colgroup: ['colgroup', Record<string, never>, ...Array<['col', { style?: string }]>] = ['colgroup', {}, ...widths.map(width => ['col', width ? { style: 'width: ' + width + 'px' } : {}] as ['col', { style?: string }])]
      return ['table', mergeAttributes(this.options.HTMLAttributes, HTMLAttributes), ...(widths.some(Boolean) ? [colgroup] : []), ['tbody', 0]]
    },
  }).configure({ resizable: true, View: EditorialTableView }),
  Node.create({ name: 'tableFigure', group: 'block', content: 'table caption?', parseHTML: () => [{ tag: 'figure.table' }], renderHTML: ({ HTMLAttributes }) => ['figure', mergeAttributes({ class: 'table' }, HTMLAttributes), 0] }),
  Node.create({ name: 'caption', content: 'inline*', parseHTML: () => [{ tag: 'figcaption' }, { tag: 'caption' }], renderHTML: () => ['figcaption', 0] }),
  HtmlAttributes(adapters), CodeBlock, RawObject(adapters), ResourceCard(adapters), mathNode('inline', adapters.editMath), mathNode('block', adapters.editMath), Checklist, ChecklistItem, ...(adapters.profile === 'document' ? [DocumentImage(adapters, false), DocumentImage(adapters, true)] : [])]
}

/** Resolve links in the editing view only; the model continues to carry canonical URIs. */
export function resolveEditorLinks(editor: Editor): void {
  editor.view.dom.querySelectorAll<HTMLAnchorElement>('[contenteditable="false"] a[href]').forEach(link => {
    const canonical = link.dataset.richReference ?? link.getAttribute('href') ?? ''
    const href = richLinkHref(canonical)
    if (href) { link.dataset.richReference = canonical; link.setAttribute('href', href) }
  })
}

export function storedEditorHtml(editor: Editor, profile: ContentProfile): string {
  return sanitizeRichHtml(editor.getHTML(), profile)
}
