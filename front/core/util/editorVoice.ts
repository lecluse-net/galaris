import type { ComputedRef, Ref } from 'vue'
import { modules as activeModules } from '@/modules'

/** Application-owned audio controls, independent of the HTML editing engine. */
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

export interface EditorVoiceContext {
  html: () => string
  editable: () => boolean
  playbackElement: () => HTMLAudioElement | undefined
  insert: (text: string) => void
}

export interface EditorVoiceSession {
  controls: ComputedRef<EditorVoiceControls>
  error: Ref<string>
  stop: () => void
}

export type EditorVoiceProvider = (context: EditorVoiceContext) => EditorVoiceSession

// The active application module supplies personal audio; core owns only the editor port.
const sources = import.meta.glob<{ default: EditorVoiceProvider }>('../../app/*/editorVoice.ts', { eager: true })
export const editorVoiceProvider = Object.entries(sources)
  .find(([path]) => activeModules.includes(`app/${path.split('/')[3]}`))?.[1].default
