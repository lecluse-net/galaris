import { ButtonView, DropdownView, ToolbarView, View, IconBoxWithMarker, type Editor, type Locale } from 'ckeditor5'
import bootstrapPdfIcon from './icons/bootstrap/file-earmark-pdf-fill.svg?raw'
import { solaireCss as solaire } from './solaireTheme'

// Bootstrap Icons (MIT): icons/bootstrap/LICENSE. Preserve red inside CKEditor's icon styles.
const pdfEditorIcon = bootstrapPdfIcon.replaceAll('<path ', `<path style="fill: ${solaire.red.accent}" `)
const headingIcon = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4 4h3v6h10V4h3v16h-3v-7H7v7H4z"/></svg>'

export function editorToolbarGroups(document: boolean, voice = false) {
  return [
    { name: 'reading', rows: [...(voice ? [['documentDictation', 'documentReading']] : []), [...(document ? ['documentLayout'] : []), 'sourceEditing', 'fullscreen']] },
    { name: 'editing', rows: document
      ? [['undo', 'redo', 'findAndReplace', 'selectAll'], ['removeFormat', 'documentPrint', 'documentExportPdf', 'documentExportBundle']]
      : [['undo', 'redo', 'findAndReplace'], ['selectAll', 'removeFormat']] },
    { name: 'text', rows: [['fontFamily', 'fontSize', 'bold', 'italic', 'underline'], ['strikethrough', 'subscript', 'superscript', 'code', 'fontColor', 'fontBackgroundColor', 'highlight']] },
    { name: 'paragraph', rows: [['heading', 'style'], ['bulletedList', 'numberedList', 'alignment', 'outdent', 'indent']] },
    { name: 'insert', rows: [['link', 'galarisLink', ...(document ? ['uploadImage', 'documentAttachments'] : []), 'insertTable'], ['blockQuote', 'codeBlock', 'horizontalLine', 'specialCharacters']] },
  ]
    .filter(group => document || group.name !== 'insert')
    .map(group => ({ ...group, items: group.rows.flat() }))
}

class ToolbarGroupView extends View {
  readonly items = this.createCollection()

  constructor(locale: Locale, name: string, label: string, rows: View[][]) {
    super(locale)
    this.items.addMany(rows.flat())
    this.setTemplate({
      tag: 'div',
      attributes: { class: ['ck', 'galaris-toolbar-group', `galaris-toolbar-group--${name}`], role: 'group', 'aria-label': label },
      children: [
        { tag: 'span', attributes: { class: ['ck', 'galaris-toolbar-group__title'], 'aria-hidden': 'true' }, children: [label] },
        {
          tag: 'div', attributes: { class: ['ck', 'galaris-toolbar-group__commands'] },
          children: rows.map(items => ({
            tag: 'div', attributes: { class: ['ck', 'galaris-toolbar-group__row'] }, children: items,
          })),
        },
      ],
    })
  }
}

export function registerEditorToolbarGroups(editor: Editor, document: boolean, translate: (key: string) => string, voice = false): void {
  for (const group of editorToolbarGroups(document, voice)) {
    editor.ui.componentFactory.add('galarisGroup' + group.name, locale => new ToolbarGroupView(
      locale, group.name, translate('richEditor.groups.' + group.name),
      group.rows.map(row => row.map(name => {
        const view = editor.ui.componentFactory.create(name)
        if (name === 'documentExportPdf' && view instanceof ButtonView) view.icon = pdfEditorIcon
        return view
      })),
    ))
  }
  editor.ui.componentFactory.add('galarisMobileToolbar', locale => {
    const toolbar = new ToolbarView(locale)
    toolbar.class = 'galaris-mobile-toolbar'
    toolbar.render()
    toolbar.fillFromConfig([
      'undo', 'redo', 'bold', 'italic', 'removeFormat', 'heading', 'style', 'bulletedList', 'numberedList',
      ...(voice ? ['documentDictation', 'documentReading'] : []),
      'link', 'galarisLink', ...(document ? ['uploadImage', 'documentAttachments'] : []),
      ...(document ? ['documentShare'] : []),
    ], editor.ui.componentFactory)
    for (const item of toolbar.items) {
      if (!(item instanceof DropdownView)) continue
      if (item.element?.classList.contains('ck-heading-dropdown')) item.buttonView.icon = headingIcon
      if (item.element?.classList.contains('ck-style-dropdown') || item.buttonView.label === editor.t('Styles')) item.buttonView.icon = IconBoxWithMarker
      if (!item.buttonView.icon) item.buttonView.icon = IconBoxWithMarker
      item.buttonView.withText = false
    }
    return toolbar
  })
}

export function editorToolbarCommands(editor: Editor): View[] {
  return [...(editor.ui.view.toolbar?.items ?? [])].flatMap(item => item instanceof ToolbarGroupView || item instanceof ToolbarView ? [...item.items] : [item])
}

/** Keep the native toolbar's arrow-key navigation continuous across visual groups. */
export function attachEditorToolbarGroups(editor: Editor): void {
  const toolbar = editor.ui.view.toolbar
  if (!toolbar) return
  toolbar.class = 'galaris-toolbar'
  for (const item of editorToolbarCommands(editor)) {
    if (item instanceof ButtonView || item instanceof DropdownView) {
      toolbar.focusables.add(item)
      toolbar.focusTracker.add(item)
    }
  }
  attachToolbarSizing(editor)
}

/** Use one command row only when all visible groups fit in the toolbar. */
function attachToolbarSizing(editor: Editor): void {
  const toolbar = editor.ui.view.toolbar?.element
  const container = toolbar?.querySelector<HTMLElement>('.ck-toolbar__items')
  if (!toolbar || !container) return
  const groups = [...container.querySelectorAll<HTMLElement>('.galaris-toolbar-group')].map(element => ({
    element,
    title: element.querySelector<HTMLElement>('.galaris-toolbar-group__title')!,
    commands: element.querySelector<HTMLElement>('.galaris-toolbar-group__commands')!,
    controls: [...element.querySelectorAll<HTMLElement>('.galaris-toolbar-group__row > *')],
  }))
  const pixels = (value: string): number => Number.parseFloat(value) || 0
  let frame = 0
  const update = (): void => {
    frame = 0
    const containerStyle = getComputedStyle(container)
    const available = container.clientWidth - pixels(containerStyle.paddingLeft) - pixels(containerStyle.paddingRight)
    if (!available) return
    const required = groups.reduce((total, group) => {
      const style = getComputedStyle(group.element)
      const gap = pixels(getComputedStyle(group.commands).columnGap)
      const controlsWidth = group.controls.reduce((width, control) => {
        const controlStyle = getComputedStyle(control)
        return width + control.getBoundingClientRect().width + pixels(controlStyle.marginLeft) + pixels(controlStyle.marginRight)
      }, 0) + gap * Math.max(0, group.controls.length - 1)
      return total + Math.max(controlsWidth, group.title.getBoundingClientRect().width)
        + pixels(style.paddingLeft) + pixels(style.paddingRight)
        + pixels(style.borderLeftWidth) + pixels(style.borderRightWidth)
    }, pixels(containerStyle.columnGap) * Math.max(0, groups.length - 1))
    toolbar.classList.toggle('galaris-toolbar--single-row', Math.ceil(required) <= available)
  }
  const observer = new ResizeObserver(() => {
    if (!frame) frame = requestAnimationFrame(update)
  })
  observer.observe(container)
  for (const group of groups) {
    observer.observe(group.title)
    for (const control of group.controls) observer.observe(control)
  }
  editor.on('destroy', () => {
    observer.disconnect()
    cancelAnimationFrame(frame)
  })
}
