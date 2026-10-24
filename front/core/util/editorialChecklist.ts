import { Node, mergeAttributes } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'

/** Only the list and its checked attributes are saved; controls belong to the editor. */
export const Checklist = Node.create({
  name: 'checklist', group: 'block list', content: 'checklistItem+',
  parseHTML: () => [{ tag: 'ul.galaris-checklist', priority: 100 }],
  renderHTML: ({ HTMLAttributes }) => ['ul', mergeAttributes(HTMLAttributes, { class: 'galaris-checklist' }), 0],
})

export const ChecklistItem = Node.create({
  name: 'checklistItem', content: 'paragraph block*', defining: true,
  addAttributes: () => ({ checked: {
    default: false,
    parseHTML: element => element.getAttribute('data-checked') === 'true',
    renderHTML: attributes => ({ 'data-checked': String(attributes.checked === true) }),
  } }),
  parseHTML: () => [{ tag: 'ul.galaris-checklist > li', priority: 100 }],
  renderHTML: ({ HTMLAttributes }) => ['li', HTMLAttributes, 0],
  addKeyboardShortcuts() { return {
    Enter: () => this.editor.commands.splitListItem(this.name, { checked: false }) || this.editor.commands.liftListItem(this.name),
    Tab: () => this.editor.commands.sinkListItem(this.name),
    'Shift-Tab': () => this.editor.commands.liftListItem(this.name),
  } },
  addNodeView: () => ({ node: initialNode, editor, getPos }) => {
    let node = initialNode
    const dom = document.createElement('li'), control = document.createElement('span')
    const checkbox = document.createElement('input'), contentDOM = document.createElement('div')
    control.contentEditable = 'false'
    control.className = 'editorial-checklist-control'
    checkbox.type = 'checkbox'
    control.append(checkbox)
    dom.append(control, contentDOM)
    const sync = (): void => {
      dom.dataset.checked = String(node.attrs.checked === true)
      checkbox.checked = node.attrs.checked === true
      checkbox.disabled = !editor.isEditable
      checkbox.setAttribute('aria-label', node.textContent || '☐')
    }
    const change = (): void => {
      const pos = getPos()
      if (editor.isEditable && pos !== undefined) editor.commands.command(({ tr }) => {
        closeHistory(tr)
        tr.setNodeMarkup(pos, undefined, { ...node.attrs, checked: checkbox.checked })
        return true
      })
      sync()
    }
    checkbox.addEventListener('change', change)
    editor.on('transaction', sync)
    sync()
    return { dom, contentDOM,
      update: next => { if (next.type !== node.type) return false; node = next; sync(); return true },
      stopEvent: event => control.contains(event.target as globalThis.Node),
      ignoreMutation: mutation => mutation.type !== 'selection' && (mutation.target === dom || control.contains(mutation.target)),
      destroy: () => { checkbox.removeEventListener('change', change); editor.off('transaction', sync) },
    }
  },
})
