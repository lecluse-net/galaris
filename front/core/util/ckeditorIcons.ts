import {
  ButtonView, DropdownView, SplitButtonView, ViewCollection, type View, type Editor,
  IconUndo, IconRedo, IconBold, IconItalic, IconUnderline, IconStrikethrough,
  IconIndent, IconOutdent, IconAlignLeft, IconAlignCenter, IconAlignRight, IconAlignJustify,
  IconLink, IconBrowseFiles, IconImage, IconImageUpload, IconFindReplace, IconSelectAll,
  IconRemoveFormat, IconFullscreenEnter, IconFullscreenLeave, IconSource, IconCodeBlock,
  IconTable, IconSpecialCharacters,
} from 'ckeditor5'

/** CKEditor's SVG icon container displays the original 24px GNOME PNG at its native size. */
export function gnomeEditorIcon(name: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><image data-gnome-icon="${name}" href="${import.meta.env.BASE_URL}editor-icons/gnome/24x24/${name}.png" width="24" height="24"/></svg>`
}

const replacements = new Map<string, string>([
  [IconUndo, gnomeEditorIcon('edit-undo')],
  [IconRedo, gnomeEditorIcon('edit-redo')],
  [IconBold, gnomeEditorIcon('format-text-bold')],
  [IconItalic, gnomeEditorIcon('format-text-italic')],
  [IconUnderline, gnomeEditorIcon('format-text-underline')],
  [IconStrikethrough, gnomeEditorIcon('format-text-strikethrough')],
  [IconIndent, gnomeEditorIcon('format-indent-more')],
  [IconOutdent, gnomeEditorIcon('format-indent-less')],
  [IconAlignLeft, gnomeEditorIcon('format-justify-left')],
  [IconAlignCenter, gnomeEditorIcon('format-justify-center')],
  [IconAlignRight, gnomeEditorIcon('format-justify-right')],
  [IconAlignJustify, gnomeEditorIcon('format-justify-fill')],
  [IconLink, gnomeEditorIcon('insert-link')],
  [IconBrowseFiles, gnomeEditorIcon('document-open')],
  [IconImage, gnomeEditorIcon('insert-image')],
  [IconImageUpload, gnomeEditorIcon('insert-image')],
  [IconFindReplace, gnomeEditorIcon('edit-find-replace')],
  [IconSelectAll, gnomeEditorIcon('edit-select-all')],
  [IconRemoveFormat, gnomeEditorIcon('edit-clear')],
  [IconFullscreenEnter, gnomeEditorIcon('view-fullscreen')],
  [IconFullscreenLeave, gnomeEditorIcon('view-restore')],
  [IconSource, gnomeEditorIcon('text-x-script')],
  [IconCodeBlock, gnomeEditorIcon('text-x-script')],
  [IconTable, gnomeEditorIcon('x-office-spreadsheet')],
  [IconSpecialCharacters, gnomeEditorIcon('accessories-character-map')],
])

/** Keep native button state, shortcuts and dynamic icons, including lazy dropdown panels. */
export function attachGnomeEditorIcons(editor: Editor): void {
  const seen = new WeakSet<object>()
  function collection(items: ViewCollection): void {
    if (seen.has(items)) return
    seen.add(items)
    for (const item of items) decorate(item)
    editor.listenTo(items, 'add', (_event, item: View) => decorate(item))
  }
  function decorate(view: View): void {
    if (seen.has(view)) return
    seen.add(view)
    if (view instanceof ButtonView || view instanceof SplitButtonView) {
      const update = () => {
        const icon = typeof view.icon === 'string' ? replacements.get(view.icon) : undefined
        if (icon) view.icon = icon
      }
      update()
      editor.listenTo(view, 'change:icon', update)
    }
    if (view instanceof DropdownView) {
      decorate(view.buttonView)
      decorate(view.panelView)
    }
    if ('children' in view && view.children instanceof ViewCollection) collection(view.children)
    if ('items' in view && view.items instanceof ViewCollection) collection(view.items)
  }
  const toolbar = editor.ui.view.toolbar
  if (toolbar) decorate(toolbar)
}
