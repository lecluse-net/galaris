/** Shared GNOME 2.20 artwork for the main toolbar and contextual commands. */
const icons: Record<string, string> = {
  undo: 'edit-undo', redo: 'edit-redo', bold: 'format-text-bold', italic: 'format-text-italic', underline: 'format-text-underline', strike: 'format-text-strikethrough',
  'shortcuts.indent': 'format-indent-more', 'shortcuts.outdent': 'format-indent-less', link: 'insert-link', galarisLink: 'document-open',
  find: 'edit-find-replace', selectAll: 'edit-select-all', removeFormat: 'edit-clear', source: 'text-x-script', insertTable: 'x-office-spreadsheet',
  specialCharacters: 'accessories-character-map', print: 'document-print', 'layout.full': 'stock_zoom-page-width', 'resources.uploadFile': 'insert-image',
  help: 'preferences-desktop-keyboard',
  left: 'format-justify-left', center: 'format-justify-center', right: 'format-justify-right', justify: 'format-justify-fill',
  fullscreen: 'view-fullscreen', restore: 'view-restore', copy: 'edit-copy', open: 'document-open', edit: 'gtk-edit', image: 'insert-image',
  insertBefore: 'go-up', insertAfter: 'go-down', remove: 'edit-delete',
  addRowBefore: 'stock_insert-rows', addRow: 'stock_insert-rows', deleteRow: 'stock_delete-row',
  addColumnBefore: 'stock_insert-columns', addColumn: 'stock_insert-columns', deleteColumn: 'stock_delete-column',
  headerRow: 'stock_select-row', mergeCells: 'stock_table-combine', splitCell: 'stock_table-split',
  tableProperties: 'document-properties', cellProperties: 'stock_table-borders', deleteTable: 'edit-delete', tableStyles: 'stock_choose-themes',
}

export function editorialIcon(key: string, fallback: string): string {
  return icons[key] ? `img:${import.meta.env.BASE_URL}editor-icons/gnome/24x24/${icons[key]}.png` : fallback
}
