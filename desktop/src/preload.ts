import { contextBridge, ipcRenderer } from 'electron'
import type { DesktopAPI, DesktopState, LocalMcpState, TabsState } from './contracts.ts'

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
  back: () => ipcRenderer.invoke('desktop:back'),
  forward: () => ipcRenderer.invoke('desktop:forward'),
  reload: () => ipcRenderer.invoke('desktop:reload'),
  showMenu: () => ipcRenderer.invoke('desktop:show-menu'),
  openMcpSettings: () => ipcRenderer.invoke('desktop:mcp-open'),
  closeMcpSettings: () => ipcRenderer.invoke('desktop:mcp-close'),
  mcpState: () => ipcRenderer.invoke('desktop:mcp-state'),
  discoverMcp: () => ipcRenderer.invoke('desktop:mcp-discover'),
  importMcp: () => ipcRenderer.invoke('desktop:mcp-import'),
  shareMcp: (id, enabled) => ipcRenderer.invoke('desktop:mcp-share', id, enabled),
  screenState: () => ipcRenderer.invoke('desktop:screen-state'),
  screenSources: () => ipcRenderer.invoke('desktop:screen-sources'),
  screenSelect: id => ipcRenderer.invoke('desktop:screen-select', id),
  screenRestore: () => ipcRenderer.invoke('desktop:screen-restore'),
  screenFinish: image => ipcRenderer.invoke('desktop:screen-finish', image),
  onMcpState(listener) {
    const handler = (_event: Electron.IpcRendererEvent, state: LocalMcpState) => listener(state)
    ipcRenderer.on('desktop:mcp-changed', handler)
    return () => ipcRenderer.removeListener('desktop:mcp-changed', handler)
  },
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
