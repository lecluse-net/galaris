import { ButtonView, SplitButtonView, createDropdown, addToolbarToDropdown, type Editor } from 'ckeditor5'
import { watchEffect } from 'vue'
import { solaireCss as solaire } from './solaireTheme'

/** Application-owned audio actions; the editor only supplies their toolbar and caret. */
export interface EditorVoiceControls {
  dictating: boolean
  dictationPending: boolean
  reading: boolean
  paused: boolean
  buffering: boolean
  labels: { dictate: string; finishDictation: string; processing: string; read: string; reading: string; paused: string; pause: string; resume: string; stop: string; readingControls: string }
  toggleDictation: () => void
  read: (selectedHtml?: string) => void
  togglePause: () => void
  stop: () => void
}

const icon = (path: string, color: string = solaire.blue.accent) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path style="fill: ${color}" d="${path}"/></svg>`
const microphoneIcon = icon('M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.93V21h2v-3.07A7 7 0 0 0 19 11z')
const stopIcon = icon('M6 6h12v12H6z', solaire.red.accent)
const playIcon = icon('M8 5v14l11-7z')
const pauseIcon = icon('M6 5h4v14H6zm8 0h4v14h-4z')

export function registerEditorVoice(editor: Editor, controls: () => EditorVoiceControls | undefined): void {
  const observe = (update: () => void) => {
    const stop = watchEffect(update)
    editor.on('destroy', stop)
  }
  editor.ui.componentFactory.add('documentDictation', locale => {
    const button = new ButtonView(locale)
    button.set({ tooltip: true, isToggleable: true })
    const update = () => {
      const voice = controls()
      button.set({
        isVisible: Boolean(voice) && !editor.isReadOnly,
        isEnabled: Boolean(voice) && !editor.isReadOnly && !voice?.reading,
        isOn: Boolean(voice?.dictating || voice?.dictationPending),
        icon: voice?.dictating || voice?.dictationPending ? stopIcon : microphoneIcon,
        label: voice?.dictating ? voice.labels.finishDictation : voice?.dictationPending ? voice.labels.processing : voice?.labels.dictate ?? '',
      })
    }
    observe(update)
    editor.on('change:isReadOnly', () => {
      const voice = controls()
      if (editor.isReadOnly && (voice?.dictating || voice?.dictationPending)) voice.stop()
      update()
    })
    button.on('execute', () => {
      if (editor.isReadOnly) return
      editor.editing.view.focus()
      controls()?.toggleDictation()
    })
    return button
  })
  editor.ui.componentFactory.add('documentReading', locale => {
    const button = new SplitButtonView(locale)
    const dropdown = createDropdown(locale, button)
    button.arrowView.unbind('label')
    const pause = new ButtonView(locale), stop = new ButtonView(locale)
    pause.set({ withText: true }); stop.set({ withText: true, icon: stopIcon })
    addToolbarToDropdown(dropdown, [pause, stop], { isVertical: true })
    dropdown.buttonView.set({ tooltip: true })
    observe(() => {
      const voice = controls()
      button.arrowView.label = voice?.labels.readingControls ?? ''
      dropdown.isEnabled = Boolean(voice) && !voice?.dictating && !voice?.dictationPending
      dropdown.buttonView.set({
        icon: voice?.reading && !voice.paused ? pauseIcon : playIcon,
        isOn: Boolean(voice?.reading),
        label: voice?.reading ? (voice.paused ? voice.labels.paused : voice.labels.reading) : voice?.labels.read ?? '',
      })
      pause.set({ label: voice?.paused ? voice.labels.resume : voice?.labels.pause ?? '', icon: voice?.paused ? playIcon : pauseIcon, isEnabled: Boolean(voice?.reading) })
      stop.isEnabled = Boolean(voice?.reading)
      stop.label = voice?.labels.stop ?? ''
      if (!voice?.reading) dropdown.isOpen = false
    })
    button.on('execute', () => {
      dropdown.isOpen = false
      if (controls()?.reading) { controls()?.togglePause(); return }
      const selection = editor.model.document.selection
      const selectedHtml = selection.isCollapsed ? undefined : editor.data.stringify(editor.model.getSelectedContent(selection))
      controls()?.read(selectedHtml)
    })
    pause.on('execute', () => { controls()?.togglePause(); dropdown.isOpen = false })
    stop.on('execute', () => { controls()?.stop(); dropdown.isOpen = false })
    return dropdown
  })
}
