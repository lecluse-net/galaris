import { contextBridge, ipcRenderer } from 'electron'
import type { DesktopAPI, DesktopState } from './contracts.ts'

const api: DesktopAPI = {
  state: () => ipcRenderer.invoke('desktop:state'),
  connect: (server: string) => ipcRenderer.invoke('desktop:connect', server),
  cancel: () => ipcRenderer.invoke('desktop:cancel'),
  checkUpdates: () => ipcRenderer.invoke('desktop:check-updates'),
  installUpdate: () => ipcRenderer.invoke('desktop:install-update'),
  onState(listener) {
    const handler = (_event: Electron.IpcRendererEvent, state: DesktopState) => listener(state)
    ipcRenderer.on('desktop:changed', handler)
    return () => ipcRenderer.removeListener('desktop:changed', handler)
  }
}
contextBridge.exposeInMainWorld('galarisDesktop', api)
