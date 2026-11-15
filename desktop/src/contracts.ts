export type Locale = 'en' | 'fr' | 'zh'
export type UpdateStatus = 'disabled' | 'idle' | 'checking' | 'downloading' | 'ready' | 'current' | 'error' | 'manual'
export interface DesktopState {
  server: string
  locale: Locale
  version: string
  error: '' | 'invalidServer' | 'connectionFailed' | 'saveFailed' | 'unsavedChanges' | 'updateFailed'
  connecting: boolean
  diagnosticsFailed: boolean
  update: { status: UpdateStatus; percent: number; version: string }
}
export interface DesktopAPI {
  state(): Promise<DesktopState>
  connect(server: string): Promise<void>
  cancel(): Promise<void>
  checkUpdates(): Promise<void>
  installUpdate(): Promise<void>
  onState(listener: (state: DesktopState) => void): () => void
}
