import { Node } from '@tiptap/core'
import { NodeSelection } from '@tiptap/pm/state'
import { renderMath, type MathKind } from './mathRendering'

export function mathNode(kind: MathKind, edit?: (position: number) => void) {
  const tag = kind === 'inline' ? 'span' : 'p'
  return Node.create({
    name: kind === 'inline' ? 'inlineMath' : 'blockMath',
    group: kind === 'inline' ? 'inline' : 'block', inline: kind === 'inline',
    atom: true, selectable: true, priority: 1100,
    addAttributes: () => ({ latex: { default: '', rendered: false, parseHTML: element => element.textContent ?? '' } }),
    // The shared paragraph parser has priority 2000; an explicit block formula
    // must be recognized before that general <p> rule.
    parseHTML: () => [{ tag: `${tag}[data-math="${kind}"]`, priority: 2100 }],
    renderHTML: ({ node }) => [tag, { 'data-math': kind }, String(node.attrs.latex)],
    renderText: ({ node }) => String(node.attrs.latex),
    addNodeView: () => ({ node, editor, getPos }) => {
      const dom = document.createElement(tag)
      dom.dataset.math = kind
      dom.contentEditable = 'false'
      let disposed = false, revision = 0
      const render = (latex: string) => {
        const current = ++revision
        const fragment = document.createElement('div'), formula = document.createElement(tag)
        formula.dataset.math = kind; formula.textContent = latex; fragment.append(formula)
        dom.textContent = latex
        dom.dataset.mathSource = latex
        dom.setAttribute('aria-label', latex)
        void renderMath(fragment).then(() => {
          if (!disposed && current === revision) dom.innerHTML = formula.innerHTML
        }).catch(() => { /* Keep the editable LaTeX fallback if loading fails. */ })
      }
      render(String(node.attrs.latex))
      const select = () => {
        if (!editor.isEditable || disposed) return
        const position = getPos()
        if (position !== undefined) { editor.commands.setNodeSelection(position); editor.view.focus() }
      }
      const open = () => {
        if (!editor.isEditable || disposed) return
        const position = getPos()
        if (position !== undefined) { select(); edit?.(position) }
      }
      dom.addEventListener('click', select)
      dom.addEventListener('dblclick', open)
      return {
        dom, ignoreMutation: () => true,
        update(next) { if (next.type !== node.type) return false; if (next.attrs.latex !== node.attrs.latex) render(String(next.attrs.latex)); node = next; return true },
        destroy() { disposed = true; dom.removeEventListener('click', select); dom.removeEventListener('dblclick', open) },
      }
    },
    addKeyboardShortcuts() { return { Enter: () => {
      const selection = this.editor.state.selection
      if (!(selection instanceof NodeSelection) || selection.node.type.name !== this.name || !this.editor.isEditable) return false
      edit?.(selection.from)
      return Boolean(edit)
    } } },
  })
}
