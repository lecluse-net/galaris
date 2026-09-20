import type { ComputedRef, Ref } from 'vue'
import { modules as activeModules } from '@/modules'
import type { EditorVoiceControls } from './ckeditorVoice'

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
