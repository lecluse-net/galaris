/** Writer-compatible commands for the document surface; extra Galaris commands use free chords. */
export const editorialShortcuts = [
  ['bold', 'Mod-b', 'bold'], ['italic', 'Mod-i', 'italic'], ['underline', 'Mod-u', 'underline'],
  ['strike', 'Mod-Alt-s', 'strike'],
  ['undo', 'Mod-z', 'undo'], ['redo', 'Mod-y', 'redo'], ['redo', 'Mod-Shift-z', 'redo'],
  ['selectAll', 'Mod-a', 'selectAll'], ['find', 'Mod-f', 'find'], ['find', 'Mod-h', 'find'], ['find', 'Mod-Alt-f', 'find'], ['link', 'Mod-k', 'link'],
  ['print', 'Mod-p', 'print'], ['help', 'F1', 'help'],
  ['shortcuts.toolbarFocus', 'F10', 'shortcuts.toolbarFocus'], ['shortcuts.contextFocus', 'Shift-F10', 'shortcuts.contextFocus'],
  ['shortcuts.clearDirectFormat', 'Mod-m', 'shortcuts.clearDirectFormat'],
  ['shortcuts.paragraph', 'Mod-0', 'shortcuts.heading', '0'],
  ...[1, 2, 3, 4, 5, 6].map(level => ['headingLevel', 'Mod-Alt-' + level, 'shortcuts.heading', String(level)] as const),
  ['left', 'Mod-l', 'alignment', 'left'], ['center', 'Mod-e', 'alignment', 'center'],
  ['right', 'Mod-r', 'alignment', 'right'], ['justify', 'Mod-j', 'alignment', 'justify'],
  ['fullscreen', 'Mod-Shift-j', 'fullscreen'],
  ['superscript', 'Mod-Shift-p', 'superscript'], ['subscript', 'Mod-Shift-b', 'subscript'],
  ['orderedList', 'F12', 'orderedList'], ['bulletList', 'Shift-F12', 'bulletList'],
  ['shortcuts.clearList', 'Mod-Shift-F12', 'shortcuts.clearList'], ['table', 'Mod-F12', 'shortcuts.table'],
  ['quote', 'Mod-Shift-9', 'quote'], ['shortcuts.inlineCode', 'Mod-Alt-e', 'shortcuts.inlineCode'], ['code', 'Mod-Alt-c', 'code'],
  ['shortcuts.indent', 'Mod-]', 'shortcuts.indent'], ['shortcuts.outdent', 'Mod-[', 'shortcuts.outdent'],
  ['shortcuts.nonbreakingSpace', 'Mod-Shift-Space', 'shortcuts.insertText', '\u00a0'],
  ['shortcuts.softHyphen', 'Mod-Minus', 'shortcuts.insertText', '\u00ad'],
  ['shortcuts.nonbreakingHyphen', 'Mod-Shift-Minus', 'shortcuts.insertText', '\u2011'],
] as const

export const readingShortcutCommands = new Set(['help', 'print', 'fullscreen', 'selectAll', 'shortcuts.toolbarFocus', 'shortcuts.contextFocus'])

/** Firefox also reports AltGraph for Ctrl+Alt (Windows) and Option (macOS).
 * Track the actual AltGr key separately so those shortcuts remain usable. */
export function isAltGraphInput(event: KeyboardEvent, altGraphPressed: boolean): boolean {
  return altGraphPressed || event.key === 'AltGraph'
    || event.getModifierState('AltGraph') && !event.ctrlKey && !event.metaKey
}

export function documentShortcut(event: KeyboardEvent, altGraphPressed = false): typeof editorialShortcuts[number] | undefined {
  if (event.isComposing || isAltGraphInput(event, altGraphPressed)) return
  return editorialShortcuts.find(([, binding]) => {
    const parts = binding.split('-'), key = parts.at(-1)!
    if (parts.includes('Mod') !== (event.ctrlKey || event.metaKey) || parts.includes('Alt') !== event.altKey || parts.includes('Shift') !== event.shiftKey) return false
    if (/^\d$/.test(key)) return event.code === 'Digit' + key
    if (key === 'Space') return event.code === 'Space'
    if (key === 'Minus') return event.code === 'Minus' || event.key === '-'
    return event.key.toLowerCase() === key.toLowerCase()
      || event.altKey && /^[a-z]$/i.test(key) && event.code === 'Key' + key.toUpperCase()
  })
}

export function shortcutKeys(binding: string, safari = false): string {
  return binding.split('-').map(key => key === 'Mod' ? safari ? 'Cmd' : 'Ctrl' : key === 'Minus' ? '−' : key.length === 1 ? key.toUpperCase() : key).join('+')
}
