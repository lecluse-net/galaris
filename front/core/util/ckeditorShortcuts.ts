import { env, type Editor, type ViewDocumentTabEvent } from 'ckeditor5'

/** Document-only shortcuts. Commands retain CKEditor's selection, undo and read-only rules. */
export function attachDocumentShortcuts(editor: Editor, translate: (key: string, values?: Record<string, number>) => string): void {
  const execute = (command: string, value?: string): boolean => {
    if (editor.isReadOnly || editor.editing.view.document.isComposing || !editor.commands.get(command)?.isEnabled) return false
    editor.execute(command, ...(value ? [{ value }] : []))
    return true
  }
  const shortcuts = [
    { keys: 'Ctrl+Shift+S', command: 'strikethrough', label: 'strike' },
    { keys: 'Ctrl+E', command: 'code', label: 'shortcuts.inlineCode' },
    { keys: 'Ctrl+Alt+C', command: 'codeBlock', label: 'code' },
    { keys: 'Ctrl+M', command: 'indent', label: 'shortcuts.indent' },
    { keys: 'Ctrl+Shift+M', command: 'outdent', label: 'shortcuts.outdent' },
  ]
  for (const shortcut of shortcuts) {
    editor.keystrokes.set(shortcut.keys, (_event, cancel) => {
      if (execute(shortcut.command)) cancel()
    }, { priority: 'high' })
  }

  // IndentBlock otherwise gives Tab to the whole list before List can nest its item.
  editor.listenTo<ViewDocumentTabEvent>(editor.editing.view.document, 'tab', (event, data) => {
    if (editor.model.document.selection.getFirstPosition()?.parent.is('element', 'codeBlock')) return
    if (execute(data.shiftKey ? 'outdentList' : 'indentList')) {
      data.preventDefault()
      data.stopPropagation()
      event.stop()
    }
  }, { context: 'li', priority: 'highest' })

  const blocks = [
    { command: 'paragraph', label: translate('richEditor.shortcuts.paragraph') },
    ...Array.from({ length: 6 }, (_, index) => ({
      command: 'heading', value: `heading${index + 1}`, label: translate('richEditor.headingLevel', { level: index + 1 }),
    })),
    { command: 'numberedList', label: translate('richEditor.orderedList') },
    { command: 'bulletedList', label: translate('richEditor.bulletList') },
    { command: 'blockQuote', label: translate('richEditor.quote') },
  ]
  // Use the number-row position: Shift changes event.key on QWERTY and AZERTY.
  // Listen only inside the editing view, leaving source fields and other editors alone.
  editor.editing.view.document.on('keydown', (event, data) => {
    const keyboard = data.domEvent
    const primary = env.isMac || env.isiOS ? keyboard.metaKey && !keyboard.ctrlKey : keyboard.ctrlKey && !keyboard.metaKey
    if (!primary || !keyboard.shiftKey || keyboard.altKey || keyboard.isComposing || !/^Digit[0-9]$/.test(keyboard.code)) return
    const block = blocks[Number(keyboard.code.slice(-1))]!
    if (execute(block.command, 'value' in block ? block.value : undefined)) {
      data.preventDefault()
      data.stopPropagation()
      event.stop()
    }
  }, { priority: 'high' })
  editor.accessibility.addKeystrokeInfos({
    keystrokes: [
      ...shortcuts.map(shortcut => ({ keystroke: shortcut.keys, label: translate('richEditor.' + shortcut.label) })),
      ...blocks.map((block, digit) => ({ keystroke: `Ctrl+Shift+${digit}`, label: block.label })),
    ],
  })
}
