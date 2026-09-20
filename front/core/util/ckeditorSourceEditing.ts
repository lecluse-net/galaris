import { Plugin, SourceEditing } from 'ckeditor5'
import hljs from 'highlight.js/lib/core'
import xml from 'highlight.js/lib/languages/xml'
import javascript from 'highlight.js/lib/languages/javascript'
import css from 'highlight.js/lib/languages/css'
import './solaireTheme'
import './ckeditorSourceEditing.css'

const highlighter = hljs.newInstance()
highlighter.registerLanguage('xml', xml)
highlighter.registerLanguage('javascript', javascript)
highlighter.registerLanguage('css', css)

/** Color only the display layer; CKEditor's textarea remains the source of truth. */
export class GalarisSourceEditing extends Plugin {
  static get pluginName() { return 'GalarisSourceEditing' as const }
  static get requires() { return [SourceEditing] as const }

  private cleanups: Array<() => void> = []

  init(): void {
    const source = this.editor.plugins.get(SourceEditing)
    this.listenTo(source, 'change:isSourceEditingMode', () => {
      this.clear()
      if (!source.isSourceEditingMode) return
      for (const rootName of this.editor.model.document.getRootNames()) {
        const textarea = this.editor.ui.getEditableElement('sourceEditing:' + rootName)
        if (textarea instanceof HTMLTextAreaElement) this.attach(textarea)
      }
    }, { priority: 'low' })
  }

  private attach(textarea: HTMLTextAreaElement): void {
    const wrapper = textarea.parentElement
    if (!wrapper) return
    const controller = new AbortController()
    const preview = textarea.ownerDocument.createElement('pre')
    preview.className = 'galaris-source-highlight'
    preview.setAttribute('aria-hidden', 'true')
    const code = textarea.ownerDocument.createElement('code')
    preview.append(code)
    wrapper.append(preview)
    wrapper.classList.add('galaris-source-editing')
    textarea.spellcheck = false

    const syncScroll = () => {
      preview.scrollTop = textarea.scrollTop
      preview.scrollLeft = textarea.scrollLeft
    }
    const render = () => {
      // A trailing space mirrors CKEditor's sizing replica, including the final empty line.
      // Highlight.js escapes the source; the authored HTML is never inserted as active DOM.
      code.innerHTML = highlighter.highlight(textarea.value, { language: 'xml', ignoreIllegals: true }).value + ' '
      syncScroll()
    }
    textarea.addEventListener('input', render, { signal: controller.signal })
    textarea.addEventListener('scroll', syncScroll, { signal: controller.signal })
    render()
    this.cleanups.push(() => {
      controller.abort()
      preview.remove()
      wrapper.classList.remove('galaris-source-editing')
    })
  }

  private clear(): void {
    this.cleanups.forEach(cleanup => cleanup())
    this.cleanups = []
  }

  override destroy(): void {
    this.clear()
    super.destroy()
  }
}
