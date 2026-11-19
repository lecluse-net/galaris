import type { InjectionKey, Ref } from 'vue'

export const documentFullscreenKey: InjectionKey<Ref<boolean>> = Symbol('documentFullscreen')
export const registerDocumentFullscreenToolbarKey: InjectionKey<(() => () => void) | null> = Symbol('registerDocumentFullscreenToolbar')

/** A workspace owns the display mode and the history across document switches. */
export const documentWorkspaceViewKey: InjectionKey<{
  fullscreen: Ref<boolean>
  canGoBack: () => boolean
  canGoForward: () => boolean
  navigateHistory: (direction: -1 | 1) => Promise<void>
}> = Symbol('documentWorkspaceView')
