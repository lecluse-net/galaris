import {
  ButtonView, Collection, ContextualBalloon, IconCopy, IconNumberedList, IconReturnArrow,
  SourceEditing, ToolbarView, UIModel, addListToDropdown, clickOutsideHandler, createDropdown,
  type Editor, type ListDropdownItemDefinition, type ModelElement,
} from 'ckeditor5'
import { copyToClipboard } from 'quasar'

type Translate = (key: string) => string

export function codeBlockLanguages(t: Translate): Array<{ language: string; label: string }> {
  return [
    { language: 'plaintext', label: t('richEditor.codeTools.automatic') },
    { language: 'text', label: t('richEditor.codeTools.plainText') },
    ...[
      ['bash', 'Bash'], ['c', 'C'], ['cs', 'C#'], ['cpp', 'C++'], ['css', 'CSS'], ['diff', 'Diff'],
      ['go', 'Go'], ['graphql', 'GraphQL'], ['html', 'HTML'], ['ini', 'INI'], ['java', 'Java'],
      ['javascript', 'JavaScript'], ['json', 'JSON'], ['kotlin', 'Kotlin'], ['lua', 'Lua'],
      ['makefile', 'Makefile'], ['markdown', 'Markdown'], ['perl', 'Perl'], ['php', 'PHP'],
      ['python', 'Python'], ['r', 'R'], ['ruby', 'Ruby'], ['rust', 'Rust'], ['scss', 'SCSS'],
      ['sql', 'SQL'], ['swift', 'Swift'], ['typescript', 'TypeScript'], ['xml', 'XML'], ['yaml', 'YAML'],
    ].map(([language, label]) => ({ language: language!, label: label! })),
  ]
}

export function codeBlockText(block: ModelElement): string {
  return [...block.getChildren()].map(child => child.is('$text') ? child.data : '\n'.repeat(child.offsetSize)).join('')
}

/** Native contextual UI keeps an explicit block target while its controls have focus. */
export function attachCodeTools(editor: Editor, t: Translate, copied: (success: boolean) => void): void {
  const model = editor.model
  model.schema.extend('codeBlock', { allowAttributes: ['codeLineNumbers', 'codeNoWrap'] })
  for (const [key, attribute] of [['codeLineNumbers', 'data-code-lines'], ['codeNoWrap', 'data-code-nowrap']] as const) {
    editor.conversion.for('upcast').attributeToAttribute({
      view: { name: 'code', key: attribute, value: 'true' }, model: { key, value: true },
    })
    editor.conversion.for('downcast').attributeToAttribute({
      model: { name: 'codeBlock', key }, view: { key: attribute, value: 'true' },
    })
  }

  const balloon = editor.plugins.get(ContextualBalloon)
  const toolbar = new ToolbarView(editor.locale)
  toolbar.set({ ariaLabel: t('richEditor.codeTools.toolbar'), class: 'galaris-code-toolbar' })
  const languages = codeBlockLanguages(t)
  const language = createDropdown(editor.locale)
  language.class = 'galaris-code-language'
  language.buttonView.set({ withText: true, ariaLabel: t('richEditor.codeTools.language'), ariaLabelledBy: undefined })
  const choices = new Collection<ListDropdownItemDefinition>()
  let target: ModelElement | null = null
  let dismissed = false
  let destroyed = false
  const validTarget = () => target?.root.is('rootElement') && target.root.isAttached() && target.is('element', 'codeBlock') ? target : null
  const change = (key: string, value: string | boolean) => {
    const block = validTarget()
    if (!block || editor.isReadOnly) return
    model.change(writer => {
      // CodeBlock's native insertion converter refreshes the language label and CSS class on rename.
      if (key === 'language') writer.rename(block, 'codeBlock')
      if (value === false) writer.removeAttribute(key, block)
      else writer.setAttribute(key, value, block)
    })
    editor.editing.view.focus()
  }
  for (const option of languages) {
    const item = new UIModel({ label: option.label, withText: true, role: 'menuitemradio', isToggleable: true, isOn: false })
    choices.add({ type: 'button', model: item })
  }
  language.on('execute', event => {
    const source = event.source
    if (!(source instanceof ButtonView)) return
    const option = languages.find(option => option.label === source.label)
    if (option) change('language', option.language)
  })
  addListToDropdown(language, choices, { ariaLabel: t('richEditor.codeTools.language'), role: 'menu' })
  toolbar.items.add(language)
  const button = (key: string, icon: string, action: () => void, toggle = false) => {
    const view = new ButtonView(editor.locale)
    view.set({ label: t('richEditor.codeTools.' + key), icon, tooltip: true, isToggleable: toggle })
    view.on('execute', action)
    toolbar.items.add(view)
    return view
  }
  const lines = button('lineNumbers', IconNumberedList, () => change('codeLineNumbers', !target?.getAttribute('codeLineNumbers')), true)
  const wrap = button('wrap', IconReturnArrow, () => change('codeNoWrap', !target?.getAttribute('codeNoWrap')), true)
  button('copy', IconCopy, () => {
    const block = validTarget()
    if (block) void copyToClipboard(codeBlockText(block)).then(() => { if (!destroyed) copied(true) }, () => { if (!destroyed) copied(false) })
  })
  toolbar.render()
  const hide = () => { if (balloon.hasView(toolbar)) balloon.remove(toolbar) }
  const refresh = () => {
    if (destroyed) return
    if (editor.plugins.get(SourceEditing).isSourceEditingMode || (!editor.ui.focusTracker.isFocused && !(editor.isReadOnly && validTarget())) || dismissed) { hide(); return }
    if (!editor.isReadOnly && !toolbar.element?.contains(document.activeElement)) {
      const parent = model.document.selection.anchor?.parent
      target = parent?.is('element', 'codeBlock') ? parent : null
    }
    const block = validTarget()
    const view = block && editor.editing.mapper.toViewElement(block)
    const dom = view && editor.editing.view.domConverter.mapViewToDom(view)?.parentElement
    if (!block || !dom) { hide(); return }
    const selected = String(block.getAttribute('language') ?? 'plaintext')
    language.buttonView.label = languages.find(option => option.language === selected)?.label ?? selected
    language.isEnabled = !editor.isReadOnly
    for (const [index, item] of [...choices].entries()) {
      if ('model' in item) item.model.set('isOn', languages[index]?.language === selected)
    }
    lines.set({ isOn: !!block.getAttribute('codeLineNumbers'), isEnabled: !editor.isReadOnly })
    wrap.set({ isOn: !block.getAttribute('codeNoWrap'), isEnabled: !editor.isReadOnly })
    const position = { target: dom }
    if (balloon.hasView(toolbar)) balloon.updatePosition(position)
    else balloon.add({ view: toolbar, position })
  }
  editor.listenTo(editor.ui, 'update', refresh)
  editor.listenTo(model.document.selection, 'change:range', () => { if (model.document.selection.anchor?.parent !== target) dismissed = false })
  editor.listenTo(editor.editing.view.document, 'mousedown', (_event, data) => {
    dismissed = false
    if (editor.isReadOnly) {
      const code = data.domTarget.closest('pre')?.querySelector('code')
      const view = code && editor.editing.view.domConverter.mapDomToView(code)
      const block = view?.is('element') && editor.editing.mapper.toModelElement(view)
      target = block?.is('element', 'codeBlock') ? block : null
      refresh()
    }
  })
  editor.listenTo(editor.ui.focusTracker, 'change:isFocused', refresh)
  editor.listenTo(editor, 'change:isReadOnly', refresh)
  clickOutsideHandler({ emitter: toolbar, activator: () => balloon.hasView(toolbar), contextElements: () => [balloon.view.element!, editor.ui.getEditableElement()!], callback: () => { target = null; dismissed = true; hide() } })
  editor.ui.addToolbar(toolbar, { isContextual: true, afterBlur: () => { dismissed = true; hide() } })
  editor.keystrokes.set('Esc', (_data, cancel) => { if (balloon.hasView(toolbar) && !language.isOpen) { dismissed = true; hide(); editor.editing.view.focus(); cancel() } }, { priority: 'high' })
  editor.on('destroy', () => { destroyed = true; hide(); toolbar.destroy() })
}
