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
  tabs(): Promise<TabsState>
  newTab(): Promise<void>
  selectTab(id: number): Promise<void>
  closeTab(id: number): Promise<void>
  back(): Promise<void>
  forward(): Promise<void>
  reload(): Promise<void>
  showMenu(): Promise<void>
  onTabs(listener: (state: TabsState) => void): () => void
}
export interface TabsState {
  activeId: number
  dark: boolean | null
  surface: string
  canGoBack: boolean
  canGoForward: boolean
  tabs: { id: number; title: string; loading: boolean }[]
}
