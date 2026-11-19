import { computed, ref, watch, type Ref } from 'vue'
import { documentFormat } from '../documentFormats'
import { documentDraftKey, restoreDocumentDraft, sameDocumentDraft, type DocumentDraft } from '../documentDraft'
import { documentService } from '../services/documentService'
import type { DocumentDetail, DocumentRecord, DocumentUpdate } from '../types'

type AutosaveState = 'saved' | 'pending' | 'saving' | 'invalid' | 'error'
type DocumentShareAccess = DocumentDraft['sharing'][number]

interface DocumentAutosaveOptions {
  identity: Readonly<{ documentId: string; agentId: number | null; editable: boolean }>
  currentDocument: Ref<DocumentDetail | null>
  editorDraft: Readonly<Ref<DocumentDraft>>
  draftFromDocument: (document: DocumentDetail) => DocumentDraft
  applyEditorDraft: (draft: DocumentDraft) => void
  session: {
    userId: number | null
    active: Readonly<Ref<boolean>>
    isCurrent: () => boolean
  }
  permissions: {
    edit: Readonly<Ref<boolean>>
    share: Readonly<Ref<boolean>>
    manageOwner: Readonly<Ref<boolean>>
    requestAgentId: Readonly<Ref<number | null>>
  }
  isGoalDocument: (document: DocumentRecord) => boolean
  sharingAgents: Readonly<Ref<readonly { value: number }[]>>
  isBlocked: () => boolean
  realtime: {
    pending: { revision: number; lockVersion: number }
    generation: () => number
    refresh: () => Promise<void>
    schedule: () => void
  }
  onUpdated: (document: DocumentDetail) => void
  onReloaded: (document: DocumentDetail) => void
}

/** Owns the saved base, recovery draft and serialized writes for one document editor. */
export function useDocumentAutosave({
  identity, currentDocument, editorDraft, draftFromDocument, applyEditorDraft, session,
  permissions, isGoalDocument, sharingAgents, isBlocked, realtime, onUpdated, onReloaded,
}: DocumentAutosaveOptions) {
  const autosaveState = ref<AutosaveState>('saved')
  const lastSavedDraft = ref<DocumentDraft | null>(null)
  const conflictDocument = ref<DocumentDetail | null>(null)
  const hasUnsavedChanges = computed(() => currentDocument.value !== null
    && !sameDocumentDraft(lastSavedDraft.value, editorDraft.value))
  const canSaveDocument = computed(() => permissions.edit.value || permissions.share.value)
  let applyingDocument = false
  let saveInFlight = false
  let saveQueued = false
  let saveWaiters: Array<() => void> = []
  let autosaveTimer: ReturnType<typeof setTimeout> | undefined
  let draftTimer: ReturnType<typeof setTimeout> | undefined

  function isSaving(): boolean { return saveInFlight }
  function clearConflict(): void { conflictDocument.value = null }
  function isCurrentDocument(id: string, agentId: number | null): boolean {
    return session.isCurrent() && identity.documentId === id
      && identity.agentId === agentId && currentDocument.value?.id === id
  }
  function cancelAutosave(): void {
    clearTimeout(autosaveTimer)
    autosaveTimer = undefined
  }

  function acceptDocument(document: DocumentDetail, event: 'loaded' | 'updated'): void {
    if (currentDocument.value?.id !== document.id) conflictDocument.value = null
    applyingDocument = true
    currentDocument.value = document
    const draft = draftFromDocument(document)
    applyEditorDraft(draft)
    lastSavedDraft.value = draft
    autosaveState.value = 'saved'
    if (event === 'loaded' && identity.editable) restoreDraft(document)
    if (event !== 'loaded') { realtime.pending.revision = 0; realtime.pending.lockVersion = 0 }
    applyingDocument = false
  }

  function applyPublicDocument(document: DocumentRecord): void {
    const current = currentDocument.value
    if (current?.id !== document.id) return
    const merged: DocumentDetail = {
      ...current,
      ...document,
      payload: current.payload,
      source_refs: current.source_refs,
    }
    currentDocument.value = merged
    onUpdated(merged)
  }

  function propertyUpdate(document: DocumentDetail, base: DocumentDraft, draft: DocumentDraft): DocumentUpdate | null {
    const update: DocumentUpdate = {
      expected_revision: document.revision,
      expected_lock_version: document.lock_version,
    }
    let changed = false
    if (!isGoalDocument(document) && draft.title !== base.title) {
      update.title = draft.title
      changed = true
    }
    if (draft.content !== base.content) { update.payload = { text: draft.content }; changed = true }
    if (!sameValue(draft.keywords, base.keywords)) { update.keywords = [...draft.keywords]; changed = true }
    return changed ? update : null
  }

  async function persistSharingChange(
    document: DocumentDetail,
    targetAgentId: number,
    access: DocumentShareAccess,
  ): Promise<DocumentRecord> {
    if (access === 'none') {
      return documentService.removeManagedDocumentGrant(
        document.id,
        targetAgentId,
        currentDocument.value?.lock_version ?? document.lock_version,
      )
    }
    return documentService.setManagedDocumentGrant(
      document.id,
      targetAgentId,
      access === 'edit',
      currentDocument.value?.lock_version ?? document.lock_version,
    )
  }

  function scheduleAutosave(delay = 700): void {
    if (!session.isCurrent()) return
    if (isBlocked()) return
    if (conflictDocument.value) return
    if (applyingDocument || !canSaveDocument.value || !currentDocument.value) return
    if (!editorDraft.value.title || !editorDraft.value.owner) {
      autosaveState.value = 'invalid'
      return
    }
    if (!hasUnsavedChanges.value) {
      autosaveState.value = 'saved'
      return
    }
    if (saveInFlight) {
      saveQueued = true
      return
    }
    autosaveState.value = 'pending'
    if (autosaveTimer) clearTimeout(autosaveTimer)
    autosaveTimer = setTimeout(() => {
      autosaveTimer = undefined
      void persistAutosave()
    }, delay)
  }

  function resolveConflict(keepDraft: boolean): void {
    const latest = conflictDocument.value
    if (!latest) return
    const draft = editorDraft.value
    applyingDocument = true
    currentDocument.value = latest
    lastSavedDraft.value = draftFromDocument(latest)
    applyEditorDraft(keepDraft ? draft : lastSavedDraft.value)
    conflictDocument.value = null
    applyingDocument = false
    realtime.pending.revision = 0
    preserveDraft()
    scheduleAutosave(150)
  }

  async function mergeLatestDocument(documentId: string, generation = realtime.generation()): Promise<void> {
    const agentId = identity.agentId
    const latest = await documentService.getDocument(documentId, permissions.requestAgentId.value)
    if (generation !== realtime.generation() || !isCurrentDocument(documentId, agentId)) return
    mergeDocument(latest)
  }

  function mergeDocument(latest: DocumentDetail): void {
    const previousBase = lastSavedDraft.value
    if (!previousBase) return
    // Include edits made while the request was pending.
    const local = editorDraft.value
    const remote = draftFromDocument(latest)
    const overlapping = (Object.keys(local) as (keyof DocumentDraft)[]).some(key => !sameValue(local[key], previousBase[key]) && !sameValue(remote[key], previousBase[key]) && !sameValue(local[key], remote[key]))
    if (overlapping) {
      conflictDocument.value = latest
      autosaveState.value = 'error'
      realtime.pending.revision = 0
      preserveDraft()
      return
    }
    const choose = <T>(localValue: T, previousValue: T, remoteValue: T): T => (
      sameValue(localValue, previousValue) ? remoteValue : localValue
    )
    const sharing: Record<number, DocumentShareAccess> = {}
    for (const key of new Set([...Object.keys(local.sharing), ...Object.keys(previousBase.sharing), ...Object.keys(remote.sharing)])) {
      const id = Number(key)
      const access = choose(
        local.sharing[id] ?? 'none',
        previousBase.sharing[id] ?? 'none',
        remote.sharing[id] ?? 'none',
      )
      if (access !== 'none') sharing[id] = access
    }
    const merged: DocumentDraft = {
      owner: choose(local.owner, previousBase.owner, remote.owner),
      title: choose(local.title, previousBase.title, remote.title),
      content: choose(local.content, previousBase.content, remote.content),
      keywords: choose(local.keywords, previousBase.keywords, remote.keywords),
      globalAccess: choose(
        local.globalAccess,
        previousBase.globalAccess,
        remote.globalAccess,
      ),
      sharing,
    }
    applyingDocument = true
    currentDocument.value = latest
    applyEditorDraft(merged)
    lastSavedDraft.value = remote
    applyingDocument = false
    realtime.pending.revision = 0
    autosaveState.value = sameDocumentDraft(merged, remote) ? 'saved' : 'pending'
    onUpdated(latest)
  }

  async function persistAutosave(): Promise<void> {
    // The editor may already be unmounted, with its listeners disposed, when a save completes.
    if (!session.isCurrent()) return
    if (isBlocked()) return
    if (conflictDocument.value) return
    if (realtime.pending.revision > 0) { await realtime.refresh(); return }
    const document = currentDocument.value
    const base = lastSavedDraft.value
    if (!document || !base || !canSaveDocument.value) return
    const agentId = identity.agentId
    const isCurrentWrite = () => isCurrentDocument(document.id, agentId)
    if (!isCurrentWrite()) return
    const draft = editorDraft.value
    if (!draft.title || !draft.owner) {
      autosaveState.value = 'invalid'
      return
    }
    if (saveInFlight) {
      saveQueued = true
      return
    }
    if (sameDocumentDraft(base, draft)) {
      autosaveState.value = 'saved'
      return
    }

    if (!documentFormat(document.document_format, document.format_version).validateDraft(draft.content)) { autosaveState.value = 'invalid'; return }
    saveInFlight = true
    autosaveState.value = 'saving'
    let persisted = cloneDraft(base)
    try {
      const update = permissions.edit.value ? propertyUpdate(document, base, draft) : null
      if (update) {
        if (update.payload) update.media_type = document.media_type
        const updated = await documentService.updateDocument(document.id, permissions.requestAgentId.value, update)
        if (!isCurrentWrite()) return
        applyPublicDocument(updated)
        persisted = {
          ...cloneDraft(draft),
          globalAccess: base.globalAccess,
          sharing: { ...base.sharing },
        }
        lastSavedDraft.value = cloneDraft(persisted)
      }
      if (permissions.share.value && persisted.globalAccess !== draft.globalAccess) {
        const revision = currentDocument.value?.revision ?? document.revision
        const updated = await documentService.setDocumentGlobalAccess(
          document.id,
          revision,
          currentDocument.value?.lock_version ?? document.lock_version,
          draft.globalAccess,
        )
        if (!isCurrentWrite()) return
        applyPublicDocument(updated)
        persisted.globalAccess = draft.globalAccess
        lastSavedDraft.value = cloneDraft(persisted)
      }
      if (permissions.share.value) {
        for (const agent of sharingAgents.value) {
          const initial = persisted.sharing[agent.value] ?? 'none'
          const desired = draft.sharing[agent.value] ?? 'none'
          if (initial === desired) continue
          const updated = await persistSharingChange(document, agent.value, desired)
          if (!isCurrentWrite()) return
          applyPublicDocument(updated)
          persisted.sharing[agent.value] = desired
          lastSavedDraft.value = cloneDraft(persisted)
        }
      }
      if (
        permissions.manageOwner.value
        && !isGoalDocument(document)
        && draft.owner !== base.owner
      ) {
        const [kind, rawId] = draft.owner.split(':')
        const ownerId = Number(rawId)
        if ((kind !== 'agent' && kind !== 'user') || !Number.isInteger(ownerId) || ownerId <= 0) {
          throw new Error('Invalid document owner selection.')
        }
        const revision = currentDocument.value?.revision ?? document.revision
        const updated = await documentService.changeDocumentOwner(
          document.id,
          revision,
          currentDocument.value?.lock_version ?? document.lock_version,
          kind,
          ownerId,
        )
        if (!isCurrentWrite()) return
        applyPublicDocument(updated)
        const latest = await documentService.getDocument(document.id, permissions.requestAgentId.value)
        if (isCurrentWrite()) onReloaded(latest)
        return
      }
      autosaveState.value = sameDocumentDraft(lastSavedDraft.value, editorDraft.value) ? 'saved' : 'pending'
    } catch (caught) {
      if (!isCurrentWrite()) return
      const status = (caught as { response?: { status?: unknown } }).response?.status
      if (status === 409) {
        try {
          await mergeLatestDocument(document.id)
          if (isCurrentWrite()) saveQueued = true
        } catch {
          if (isCurrentWrite()) autosaveState.value = 'error'
        }
      } else {
        autosaveState.value = 'error'
      }
    } finally {
      saveInFlight = false
      // Lifecycle/session changes already flushed the old draft; a late reply must not rewrite it.
      const current = isCurrentWrite()
      if (current) preserveDraft()
      const waiters = saveWaiters
      saveWaiters = []
      for (const resolve of waiters) resolve()
      const queued = saveQueued
      saveQueued = false
      if (current) {
        const mustRefreshExternal = realtime.pending.revision > (currentDocument.value?.revision ?? 0)
          || realtime.pending.lockVersion > (currentDocument.value?.lock_version ?? 0)
        if (mustRefreshExternal) realtime.schedule()
        else { realtime.pending.revision = 0; realtime.pending.lockVersion = 0 }
        if (queued || (autosaveState.value === 'pending' && hasUnsavedChanges.value)) scheduleAutosave(150)
      }
    }
  }

  function waitForActiveSave(): Promise<void> {
    if (!saveInFlight) return Promise.resolve()
    return new Promise(resolve => saveWaiters.push(resolve))
  }

  async function flushAutosave(): Promise<boolean> {
    cancelAutosave()
    for (let attempt = 0; attempt < 5; attempt += 1) {
      await waitForActiveSave()
      await persistAutosave()
      await waitForActiveSave()
      if (!hasUnsavedChanges.value) return true
      if (autosaveState.value === 'error' || autosaveState.value === 'invalid') return false
      cancelAutosave()
    }
    return !hasUnsavedChanges.value
  }

  async function discardDraft(): Promise<void> {
    cancelAutosave()
    await waitForActiveSave()
    saveQueued = false
    const saved = conflictDocument.value ? draftFromDocument(conflictDocument.value) : lastSavedDraft.value
    if (!saved) return
    applyingDocument = true
    if (conflictDocument.value) currentDocument.value = conflictDocument.value
    lastSavedDraft.value = cloneDraft(saved)
    applyEditorDraft(saved)
    conflictDocument.value = null
    autosaveState.value = 'saved'
    applyingDocument = false
    preserveDraft()
  }

  function draftKey(): string | null { return session.userId === null ? null : documentDraftKey(session.userId, identity.agentId, identity.documentId) }
  function scheduleDraft(): void {
    if (!identity.editable || applyingDocument || !currentDocument.value || !session.active.value) return
    // Bound the delay during continuous typing, rather than postponing recovery indefinitely.
    draftTimer ??= setTimeout(preserveDraft, 200)
  }
  function preserveDraft(): void {
    if (draftTimer) clearTimeout(draftTimer)
    draftTimer = undefined
    if (!identity.editable || applyingDocument || !currentDocument.value || !lastSavedDraft.value) return
    const key = draftKey()
    if (!key) return
    try {
      if (hasUnsavedChanges.value) sessionStorage.setItem(key, JSON.stringify({ user_id: session.userId, revision: currentDocument.value.revision, base: lastSavedDraft.value, draft: editorDraft.value }))
      else sessionStorage.removeItem(key)
    } catch { autosaveState.value = 'error' }
  }
  function restoreDraft(document: DocumentDetail): void {
    if (session.userId === null || !session.active.value) return
    try {
      const saved = restoreDocumentDraft(sessionStorage, session.userId, identity.agentId, identity.documentId)
      if (!saved) return
      applyEditorDraft(saved.draft)
      lastSavedDraft.value = cloneDraft(saved.base)
      if (saved.revision !== document.revision) {
        conflictDocument.value = document
        autosaveState.value = 'error'
        realtime.pending.revision = document.revision
      } else autosaveState.value = 'pending'
    } catch { autosaveState.value = 'error' }
  }
  function preserveHiddenDraft(): void { if (document.visibilityState === 'hidden') preserveDraft() }

  watch(editorDraft, () => { scheduleDraft(); scheduleAutosave() }, { flush: 'sync' })

  return {
    autosaveState, conflictDocument, hasUnsavedChanges, acceptDocument, resolveConflict, clearConflict,
    cancelAutosave, isSaving, scheduleAutosave, waitForActiveSave, flushAutosave,
    mergeDocument, mergeLatestDocument, discardDraft,
    draftKey, preserveDraft, preserveHiddenDraft,
  }
}

function sameValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

function cloneDraft(draft: DocumentDraft): DocumentDraft {
  return { ...draft, keywords: [...draft.keywords],
    sharing: Object.fromEntries(Object.entries(draft.sharing).filter(([, access]) => access !== 'none')) }
}
