import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { useAuthStore } from '@/core/user'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { isAxiosError } from 'axios'
import { chatService } from './services/chatService'
import { DRAFT_SYNC_MS, draftBlob, draftKey, readLocalDraft, writeLocalDraft, type DraftContent, type DraftFile, type DraftSend, type LocalDraft } from './drafts'

// A previous mount may finish its HTTP request after a new mount starts typing.
// Only the latest editor may replace that scope's local recovery snapshot.
const localOwners = new Map<string, symbol>()

/** A session owns its room even after navigation. Late responses never touch another editor. */
export function useComposerDraft(options: {
  room: () => string
  text: Ref<string>
  files: Ref<File[]>
  resources: Ref<{ uri: string; name: string }[]>
  effort: Ref<number>
  topic: () => string | null
  reply: () => string | null
  restoreContext: (topic: string | null, reply: string | null) => void
}) {
  const auth = useAuthStore()
  const authGeneration = ref(sessionGeneration())
  const refreshGeneration = (): void => { authGeneration.value = sessionGeneration() }
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, refreshGeneration)
  window.addEventListener('storage', refreshGeneration)
  const ready = ref(false)
  const saving = ref(false)
  const failed = ref(false)
  const replyId = ref<string | null>(null)
  let restoring = false
  let pageSuspended = false
  let current: Session | null = null
  const identities = new WeakMap<File, DraftFile>()
  interface Session {
    room: string; key: string; generation: string; record: LocalDraft
    blobs: Map<string, File>; writes: Promise<unknown>[]
    running: Promise<void> | null; initialized: Promise<void>; paused: boolean; removed: Set<string>; owner: symbol
  }
  function persist(session: Session): void {
    if (localOwners.get(session.key) !== session.owner) return
    try { writeLocalDraft(session.key, session.record) } catch { if (current === session) failed.value = true }
  }
  function apply(content: DraftContent | null, session: Session): void {
    if (current !== session) return
    restoring = true
    options.text.value = content?.text ?? ''
    options.resources.value = content?.resources ?? []
    options.effort.value = content?.effort ?? 2
    replyId.value = content?.reply_to_message_id ?? null
    options.files.value = (content?.files ?? []).map(item => {
      const file = session.blobs.get(item.key) ?? new File([], item.name, { type: item.mime })
      identities.set(file, item)
      return file
    })
    options.restoreContext(content?.topic_id ?? null, content?.reply_to_message_id ?? null)
    restoring = false
  }
  function capture(): void {
    const session = current
    if (restoring || !session) return
    localOwners.set(session.key, session.owner)
    const descriptors = options.files.value.map(file => {
      let item = identities.get(file)
      if (!item) {
        item = { key: crypto.randomUUID(), name: file.name, size: file.size, mime: file.type, uploaded: false }
        identities.set(file, item)
        session.blobs.set(item.key, file)
        // IndexedDB commits before upload/send; a failure is surfaced, never silently ignored.
        session.writes.push(draftBlob(session.key, item.key, file).catch(error => reportFor(session, error)))
      }
      return { ...item }
    })
    const content: DraftContent = {
      client_message_id: crypto.randomUUID(),
      text: options.text.value, files: descriptors, resources: [...options.resources.value],
      effort: options.effort.value, topic_id: options.topic(), reply_to_message_id: options.reply() ?? replyId.value,
    }
    const empty = !content.text && !content.files.length && !content.resources.length
    for (const old of session.record.content?.files ?? []) {
      if (!descriptors.some(item => item.key === old.key)) {
        session.blobs.delete(old.key)
        session.removed.add(old.key)
        void draftBlob(session.key, old.key, null).catch(error => reportFor(session, error))
      }
    }
    session.record = { ...session.record, dirty: true, mutationKey: crypto.randomUUID(), content: empty ? null : content }
    session.record.removedKeys = [...session.removed]
    persist(session)
    // File uploads start immediately, independently of the text throttle.
    if (descriptors.some(item => !item.uploaded)) void flush(session).catch(error => reportFor(session, error))
  }
  function report(_error: unknown): void {
    failed.value = true
  }
  function leave(session: Session): void {
    void flush(session).catch(error => reportFor(session, error)).finally(() => {
      if (localOwners.get(session.key) === session.owner) localOwners.delete(session.key)
    })
  }
  function reportFor(session: Session, error: unknown): void {
    if (current === session) report(error)
  }
  function canSync(session: Session): boolean {
    return !pageSuspended && session.generation === sessionGeneration()
  }
  async function flush(session: Session): Promise<void> {
    if (session.paused || !canSync(session)) return
    if (session.running) { await session.running; if (session.record.dirty) return flush(session); return }
    session.running = (async () => {
      await session.initialized
      if (!canSync(session) || localOwners.get(session.key) !== session.owner || (!session.record.dirty && !session.removed.size)) return
      if (current === session) saving.value = true
      try {
        async function cleanup(): Promise<void> {
          for (const key of session.removed) {
            if (!canSync(session)) return
            await chatService.discardDraftFile(session.room, key)
            session.removed.delete(key)
            session.record.removedKeys = [...session.removed]
            persist(session)
          }
        }
        async function push(sent: { revision: number; mutationKey: string; content: DraftContent | null }): Promise<void> {
          if (!canSync(session)) return
          session.record.pending = sent
          persist(session)
          let saved
          try {
            saved = await chatService.saveDraft(session.room, sent.revision, sent.mutationKey, sent.content)
          } catch (error) {
            if (!isAxiosError(error) || error.response?.status !== 409) throw error
            if (!canSync(session)) return
            const remote = await chatService.draft(session.room)
            if (session.generation !== sessionGeneration() || localOwners.get(session.key) !== session.owner) return
            session.record.revision = remote.revision
            delete session.record.pending
            session.record.baseClientMessageId = remote.content?.client_message_id
            if (!session.record.content && remote.content && !session.record.clearedMessageIds?.includes(remote.content.client_message_id)) {
              session.record.content = remote.content
              session.record.dirty = false
              apply(remote.content, session)
            } else {
              session.record.dirty = true
              session.record.mutationKey = crypto.randomUUID()
            }
            persist(session)
            return
          }
          if (session.generation !== sessionGeneration()) return
          session.record.revision = saved.revision
          session.record.baseClientMessageId = saved.content?.client_message_id
          if (session.record.mutationKey === sent.mutationKey) session.record.dirty = false
          delete session.record.pending
          persist(session)
        }
        // Recover the exact receipt first, even if typing continued after a lost response.
        if (session.record.pending) await push(session.record.pending)
        if (!session.record.dirty) { await cleanup(); return }
        await Promise.all(session.writes)
        session.writes = []
        for (const item of session.record.content?.files ?? []) {
          if (item.uploaded) continue
          const file = session.blobs.get(item.key)
          if (!file) throw new Error('Draft attachment missing from local storage')
          if (!canSync(session)) return
          const uploaded = await chatService.uploadDraftFile(session.room, item.key, file)
          // A deletion during upload must not reintroduce the file.
          const live = session.record.content?.files.find(value => value.key === item.key)
          if (live) Object.assign(live, uploaded)
          const identity = identities.get(file)
          if (identity) Object.assign(identity, uploaded)
          persist(session)
        }
        // A second selection can replace the file array during the first upload.
        // Do not mark that newer snapshot saved until all its bytes are durable.
        if (session.record.content?.files.some(item => !item.uploaded)) return
        const sent = JSON.parse(JSON.stringify(session.record)) as LocalDraft
        if (!sent.dirty) return
        await push({ revision: sent.revision, mutationKey: sent.mutationKey, content: sent.content })
        await cleanup()
        if (current === session) failed.value = false
      } finally { if (current === session) saving.value = false }
    })()
    try { await session.running } finally { session.running = null }
  }
  watch([options.text, options.files, options.resources, options.effort, options.topic, options.reply], capture, { deep: true, flush: 'sync' })
  watch([options.room, () => auth.user?.id, authGeneration], ([room, user]) => {
    if (current) leave(current)
    current = null
    ready.value = false
    failed.value = false
    if (!user) return
    const generation = sessionGeneration()
    const key = draftKey(user, room, generation)
    const legacyKey = draftKey(user, room)
    let legacyScope: string | null = null
    let local: LocalDraft | null = null
    try {
      local = readLocalDraft(key)
      if (!local && key !== legacyKey) {
        const legacy = readLocalDraft(legacyKey)
        if (legacy && (!legacy.recoverySession || legacy.recoverySession === generation)) {
          local = legacy
          legacyScope = legacyKey
          writeLocalDraft(legacyKey, { ...legacy, recoverySession: generation })
        }
      }
    } catch (error) { report(error) }
    const session: Session = { room, key, generation: sessionGeneration(),
      record: local ?? { revision: 0, content: null, dirty: false, mutationKey: crypto.randomUUID() },
      blobs: new Map(), writes: [], running: null, initialized: Promise.resolve(), paused: false, removed: new Set(), owner: Symbol(key) }
    current = session
    session.removed = new Set(local?.removedKeys ?? [])
    localOwners.set(key, session.owner)
    persist(session)
    apply(session.record.content, session)
    session.initialized = (async () => {
      try {
        for (const item of session.record.content?.files ?? []) {
          let file = await draftBlob(key, item.key)
          if (!file && legacyScope) {
            file = await draftBlob(legacyScope, item.key)
            if (file) await draftBlob(key, item.key, file)
          }
          if (file) session.blobs.set(item.key, file)
        }
        const remote = await chatService.draft(room)
        if (session.generation !== sessionGeneration()) return
        if (!session.record.content && (!session.record.dirty || session.record.revision !== remote.revision)
          && (!remote.content || !session.record.clearedMessageIds?.includes(remote.content.client_message_id))) {
          session.record = { ...session.record, ...remote, dirty: false }
          delete session.record.pending
          session.record.baseClientMessageId = remote.content?.client_message_id
          persist(session)
          apply(remote.content, session)
        } else if (session.record.revision !== remote.revision) {
          session.record.revision = remote.revision
          session.record.baseClientMessageId = remote.content?.client_message_id
          session.record.mutationKey = crypto.randomUUID()
          session.record.dirty = true
          delete session.record.pending
          persist(session)
        }
        // Replace local placeholders after IndexedDB has loaded, unless typing changed them.
        if (current === session) {
          restoring = true
          options.files.value = options.files.value.map(file => {
            const item = identities.get(file)
            const blob = item && session.blobs.get(item.key)
            if (blob && item) { identities.set(blob, item); return blob }
            return file
          })
          restoring = false
        }
      } catch (error) { reportFor(session, error) }
      finally { if (current === session) ready.value = true }
    })()
  }, { immediate: true, flush: 'sync' })
  const wake = (): void => {
    const session = current
    if (document.visibilityState === 'visible' && session && !session.running && !session.paused) {
      void flush(session).catch(error => reportFor(session, error))
    }
  }
  // The local snapshot already contains the latest draft. Starting XHR during
  // pagehide can fail before it leaves WebKit, even on the same origin.
  const suspendPage = (): void => { pageSuspended = true }
  const resumePage = (): void => { pageSuspended = false; wake() }
  const timer = window.setInterval(wake, DRAFT_SYNC_MS)
  window.addEventListener('online', wake)
  window.addEventListener('pagehide', suspendPage)
  window.addEventListener('pageshow', resumePage)
  document.addEventListener('visibilitychange', wake)
  onBeforeUnmount(() => {
    clearInterval(timer)
    window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, refreshGeneration)
    window.removeEventListener('storage', refreshGeneration)
    window.removeEventListener('online', wake)
    window.removeEventListener('pagehide', suspendPage)
    window.removeEventListener('pageshow', resumePage)
    document.removeEventListener('visibilitychange', wake)
    if (current) leave(current)
    current = null
  })
  async function prepare(): Promise<{ token: DraftSend; files: File[]; acknowledge: (accepted: boolean, clear: () => void) => Promise<void> } | undefined> {
    const session = current
    if (!session) return undefined
    // Publication owns its files and identity. An optional autosave must never
    // hold the send button, even when its HTTP request has not returned.
    if (session.generation !== sessionGeneration()) throw new Error('Session changed')
    if (!session.record.content) return undefined
    const sent = JSON.parse(JSON.stringify(session.record)) as LocalDraft
    const content = sent.content!
    const files: File[] = []
    for (const item of content.files.filter(item => !item.uploaded)) {
      const file = session.blobs.get(item.key) ?? await draftBlob(session.key, item.key)
      if (!file) throw new Error('Message attachment is no longer available')
      session.blobs.set(item.key, file)
      files.push(file)
    }
    if (current !== session || session.generation !== sessionGeneration()) throw new Error('Session changed')
    if (session.record.mutationKey !== sent.mutationKey) return prepare()
    const fallbackFiles = content.files.map(item => session.blobs.get(item.key))
    session.paused = true
    return { files, token: { revision: sent.revision, clientMessageId: content.client_message_id,
      replyToMessageId: content.reply_to_message_id, fileKeys: content.files.filter(item => item.uploaded).map(item => item.key),
      fallbackFiles: fallbackFiles.every((file): file is File => Boolean(file)) ? fallbackFiles : undefined }, acknowledge: async (accepted, clear) => {
      session.paused = false
      if (!accepted) return
      // The server increments the cursor while clearing only this sent revision.
      if (session.record.revision === sent.revision) session.record.revision += 1
      if (session.record.mutationKey === sent.mutationKey) {
        session.record.content = null
        session.record.dirty = true
        session.record.mutationKey = crypto.randomUUID()
        session.record.clearedMessageIds = [...new Set([content.client_message_id,
          sent.baseClientMessageId, sent.pending?.content?.client_message_id].filter((key): key is string => Boolean(key)))]
      } else if (session.record.content) {
        session.record.content.client_message_id = crypto.randomUUID()
      }
      if (current === session) {
        restoring = true
        replyId.value = null
        try { clear() } finally { restoring = false }
        if (options.text.value || options.files.value.length || options.resources.value.length) capture()
      }
      persist(session)
      for (const item of content.files) {
        session.removed.add(item.key)
        session.blobs.delete(item.key)
        void draftBlob(session.key, item.key, null).catch(error => reportFor(session, error))
      }
      session.record.removedKeys = [...session.removed]
      persist(session)
      void flush(session).catch(error => reportFor(session, error))
    } }
  }
  async function retry(replace = false): Promise<void> {
    const session = current
    if (!session) return
    if (replace) {
      const remote = await chatService.draft(session.room)
      if (current !== session) return
      session.record.revision = remote.revision
      session.record.mutationKey = crypto.randomUUID()
      delete session.record.pending
      session.record.dirty = true
      persist(session)
    }
    await flush(session)
    failed.value = false
  }
  function cancelReply(): void { replyId.value = null; capture() }
  watch(options.reply, (value, previous) => { if (value !== previous) replyId.value = value })
  return { ready, saving, failed, replyId, cancelReply, retry, prepare }
}
