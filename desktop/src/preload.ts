import { contextBridge, ipcRenderer } from 'electron'
import type { DesktopAPI, DesktopState, TabsState } from './contracts.ts'

const api: DesktopAPI = {
  state: () => ipcRenderer.invoke('desktop:state'),
  connect: (server: string) => ipcRenderer.invoke('desktop:connect', server),
  cancel: () => ipcRenderer.invoke('desktop:cancel'),
  checkUpdates: () => ipcRenderer.invoke('desktop:check-updates'),
  installUpdate: () => ipcRenderer.invoke('desktop:install-update'),
  tabs: () => ipcRenderer.invoke('desktop:tabs'),
  newTab: () => ipcRenderer.invoke('desktop:new-tab'),
  selectTab: (id: number) => ipcRenderer.invoke('desktop:select-tab', id),
  closeTab: (id: number) => ipcRenderer.invoke('desktop:close-tab', id),
  onTabs(listener) {
    const handler = (_event: Electron.IpcRendererEvent, state: TabsState) => listener(state)
    ipcRenderer.on('desktop:tabs-changed', handler)
    return () => ipcRenderer.removeListener('desktop:tabs-changed', handler)
  },
  onState(listener) {
    const handler = (_event: Electron.IpcRendererEvent, state: DesktopState) => listener(state)
    ipcRenderer.on('desktop:changed', handler)
    return () => ipcRenderer.removeListener('desktop:changed', handler)
  }
}
contextBridge.exposeInMainWorld('galarisDesktop', api)
