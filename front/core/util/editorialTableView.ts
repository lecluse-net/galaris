import { TableView } from '@tiptap/extension-table'
import type { Node } from '@tiptap/pm/model'
import type { EditorView } from '@tiptap/pm/view'

/** Resizable tables must render the same authored attributes as their saved HTML. */
export class EditorialTableView extends TableView {
  constructor(node: Node, cellMinWidth: number, view?: EditorView, attributes: Record<string, unknown> = {}) {
    super(node, cellMinWidth, view, attributes)
    this.applyEditorialAttributes()
  }

  override update(node: Node): boolean {
    if (!super.update(node)) return false
    this.applyEditorialAttributes()
    return true
  }

  private applyEditorialAttributes(): void {
    const { width, minWidth } = this.table.style
    this.table.className = this.node.attrs.editorialClass ?? ''
    this.table.style.cssText = this.node.attrs.editorialStyle ?? ''
    if (!this.table.style.width) this.table.style.width = width
    if (!this.table.style.minWidth) this.table.style.minWidth = minWidth
  }
}
