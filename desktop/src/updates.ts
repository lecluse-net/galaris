import type { DesktopState } from './contracts.ts'

/** Boundary implemented by electron-updater; also usable with a synthetic update feed. */
export interface Updater {
  autoDownload: boolean
  autoInstallOnAppQuit: boolean
  allowPrerelease: boolean
  allowDowngrade: boolean
  disableWebInstaller: boolean
  on(event: 'checking-for-update' | 'update-not-available' | 'error', listener: () => void): unknown
  on(event: 'update-available' | 'update-downloaded', listener: (info: { version: string }) => void): unknown
  on(event: 'download-progress', listener: (info: { percent: number }) => void): unknown
  checkForUpdates(): Promise<unknown>
  quitAndInstall(): void
}

export function configureUpdates(
  updater: Updater,
  initial: 'idle' | 'disabled' | 'manual',
  changed: (update: DesktopState['update']) => void,
  ready: () => void
) {
  let state: DesktopState['update'] = { status: initial, percent: 0, version: '' }
  let checking: Promise<void> | undefined
  const enabled = initial === 'idle'
  const set = (update: Partial<DesktopState['update']>) => {
    state = { ...state, ...update }
    changed({ ...state })
  }
  updater.autoDownload = true
  updater.autoInstallOnAppQuit = false
  updater.allowPrerelease = false
  updater.allowDowngrade = false
  updater.disableWebInstaller = true
  updater.on('checking-for-update', () => { if (state.status !== 'ready') set({ status: 'checking' }) })
  updater.on('update-available', info => { if (state.status !== 'ready') set({ status: 'downloading', version: info.version }) })
  updater.on('download-progress', info => { if (state.status !== 'ready') set({ status: 'downloading', percent: Math.min(100, Math.max(0, info.percent)) }) })
  updater.on('update-not-available', () => { if (state.status !== 'ready') set({ status: 'current' }) })
  updater.on('error', () => { if (state.status !== 'ready') set({ status: 'error' }) })
  updater.on('update-downloaded', info => {
    if (state.status === 'ready') return
    set({ status: 'ready', percent: 100, version: info.version })
    ready()
  })
  changed({ ...state })
  return {
    check(): Promise<void> {
      if (!enabled || state.status === 'ready' || state.status === 'downloading') return Promise.resolve()
      if (checking) return checking
      checking = Promise.resolve().then(() => updater.checkForUpdates()).then(() => undefined)
        .catch(() => { if (state.status !== 'ready') set({ status: 'error' }) })
        .finally(() => { checking = undefined })
      return checking
    },
    install(): void { if (enabled && state.status === 'ready') updater.quitAndInstall() }
  }
}
