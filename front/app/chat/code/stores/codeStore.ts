import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { isAxiosError } from 'axios'
import { codeService } from '../services/codeService'
import type { CodeSession } from '../types'

export interface RetainedEditor {
  session: CodeSession; loaded: boolean; error: boolean
  recoveryUrl?: string; recoveryLoaded?: boolean; showRecovery?: boolean
  recoveryVersion?: number; pendingRecoveryUrl?: string
}

export const useCodeStore = defineStore('code-workspace', () => {
  const editors = ref<RetainedEditor[]>([])
  const activeId = ref<string | null>(null)
  const anchor = shallowRef<HTMLElement | null>(null)
  const active = computed(() => {
    const editor = editors.value.find(item => item.session.workspace.id === activeId.value)
    return editor ? { ...editor,
      loaded: editor.showRecovery ? !!editor.recoveryLoaded : editor.loaded,
      error: editor.error || (!!editor.recoveryUrl && !editor.showRecovery),
    } : null
  })
  const pending = new Map<string, Promise<RetainedEditor>>()
  const recovering = new Set<string>()
  let generation = 0
  let touching = false

  async function open(id: string, file?: string, view?: string): Promise<RetainedEditor> {
    const existing = editors.value.find(editor => editor.session.workspace.id === id)
    if (existing) {
      if (file !== undefined || view !== undefined) await codeService.navigate(existing.session.id, file, view)
      return existing
    }
    const inflight = pending.get(id)
    if (inflight) {
      const editor = await inflight
      if (file !== undefined || view !== undefined) await codeService.navigate(editor.session.id, file, view)
      return editor
    }
    const startedIn = generation
    const request = codeService.open(id).then(async session => {
      if (startedIn !== generation) throw new Error('Session changed')
      const editor = { session, loaded: false, error: false }
      editors.value.push(editor)
      try { if (file !== undefined || view !== undefined) await codeService.navigate(session.id, file, view) }
      catch { editor.error = true }
      if (startedIn !== generation) throw new Error('Session changed')
      return editor
    }).finally(() => pending.delete(id))
    pending.set(id, request)
    return await request
  }
  function hide(): void { activeId.value = null; anchor.value = null }
  function reset(): void { generation += 1; hide(); editors.value = []; pending.clear(); recovering.clear() }
  async function recover(id: string): Promise<void> {
    const editor = editors.value.find(item => item.session.workspace.id === id)
    if (!editor) return
    const startedIn = generation
    if (recovering.has(id)) return
    if (editor.pendingRecoveryUrl) throw new Error('code_recovery_reload_required')
    // Renew access to the same IDE. Never reload a loaded frame: it may hold
    // unsaved buffers even when its cookie or server lease has expired.
    if (editor.loaded) {
      recovering.add(id)
      try {
        let workspace
        try { workspace = await codeService.touch(editor.session.id) }
        catch (error) {
          if (!isAxiosError(error) || error.response?.status !== 410) throw error
          const recovery = await codeService.resume(editor.session.id)
          if (startedIn !== generation || !editors.value.includes(editor)) return
          workspace = recovery.workspace
          if (recovery.restart_required && recovery.url) {
            if (editor.recoveryLoaded) {
              editor.pendingRecoveryUrl = recovery.url
              throw new Error('code_recovery_reload_required', { cause: error })
            }
            editor.recoveryUrl = recovery.url
            editor.recoveryVersion = (editor.recoveryVersion ?? 0) + 1
            editor.recoveryLoaded = false
            editor.showRecovery = true
          }
        }
        if (!editors.value.includes(editor)) return
        if (workspace?.id === id) editor.session.workspace = workspace
        editor.error = false
      } catch (error) {
        if (startedIn !== generation) return
        editor.error = true
        throw error
      }
      finally { if (startedIn === generation) recovering.delete(id) }
      return
    }
    const session = await codeService.open(id)
    if (startedIn !== generation || !editors.value.includes(editor)) return
    editor.session = session
    editor.error = false
  }
  function reloadRecovery(id: string): void {
    const editor = editors.value.find(item => item.session.workspace.id === id)
    if (!editor?.pendingRecoveryUrl) return
    editor.recoveryUrl = editor.pendingRecoveryUrl
    editor.pendingRecoveryUrl = undefined
    editor.recoveryVersion = (editor.recoveryVersion ?? 0) + 1
    editor.recoveryLoaded = false
    editor.showRecovery = true
    editor.error = false
  }
  async function heartbeat(): Promise<void> {
    if (touching) return
    touching = true
    try { await Promise.all(editors.value.map(async editor => {
      if (recovering.has(editor.session.workspace.id)) return
      try {
        const workspace = await codeService.touch(editor.session.id)
        if (workspace?.id === editor.session.workspace.id) editor.session.workspace = workspace
        if (editor.loaded && !editor.pendingRecoveryUrl) editor.error = false
      }
      catch { editor.error = true }
    })) } finally { touching = false }
  }
  return { editors, activeId, anchor, active, open, hide, reset, recover, reloadRecovery, heartbeat }
})
