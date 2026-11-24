export type Locale = 'en' | 'fr' | 'zh'
export type UpdateStatus = 'disabled' | 'idle' | 'checking' | 'downloading' | 'ready' | 'current' | 'error' | 'manual'
export interface ScreenRequest { id: string; expires_at: string; agent: string; reason: string }
export interface ScreenPromptState extends ScreenRequest { locale: Locale; title: string; nativePicker: boolean }
export interface ScreenSource { id: string; name: string }
export interface DesktopState {
  server: string
  settingsPage: 'server' | 'mcp'
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
  openMcpSettings(): Promise<void>
  closeMcpSettings(): Promise<void>
  mcpState(): Promise<LocalMcpState>
  discoverMcp(): Promise<void>
  importMcp(): Promise<void>
  shareMcp(id: string, enabled: boolean): Promise<void>
  onMcpState(listener: (state: LocalMcpState) => void): () => void
  screenState(): Promise<ScreenPromptState>
  screenSources(): Promise<ScreenSource[]>
  screenSelect(id: string): Promise<boolean>
  screenRestore(): Promise<void>
  screenFinish(image: ArrayBuffer | null): Promise<void>
}

export interface LocalMcpSummary {
  id: string
  name: string
  source: string
  transport: 'stdio' | 'http' | 'sse'
}

export interface LocalMcpState {
  server: string
  scanning: boolean
  unreadable: number
  error: '' | 'mcpSignIn' | 'mcpPermission' | 'mcpSaveError' | 'mcpServerError' | 'mcpLimit'
    | 'mcpLocalAuthRequired' | 'mcpLocalAccessDenied'
  entries: (LocalMcpSummary & {
    shared: boolean
    status: 'mcpPrivate' | 'mcpConnecting' | 'mcpOnline' | 'mcpOffline' | 'mcpRevoked' | 'mcpChanged' | 'mcpMissing'
  })[]
}
export interface TabsState {
  activeId: number
  dark: boolean | null
  surface: string
  canGoBack: boolean
  canGoForward: boolean
  tabs: { id: number; title: string; loading: boolean }[]
}
