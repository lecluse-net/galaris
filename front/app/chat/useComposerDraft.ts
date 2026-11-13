import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { useAuthStore } from '@/core/user'
import { sessionGeneration } from '@/core/api'
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
  error: (error: unknown) => void
}) {
  const auth = useAuthStore()
  const ready = ref(false)
  const saving = ref(false)
  const failed = ref(false)
  const conflicted = ref(false)
  const replyId = ref<string | null>(null)
  let restoring = false
  let current: Session | null = null
  const identities = new WeakMap<File, DraftFile>()
  interface Session {
    room: string; key: string; generation: string; record: LocalDraft
    blobs: Map<string, File>; writes: Promise<unknown>[]
    running: Promise<void> | null; initialized: Promise<void>; paused: boolean; removed: Set<string>; owner: symbol
  }
  function persist(session: Session): void {
    if (localOwners.get(session.key) === session.owner) writeLocalDraft(session.key, session.record)
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
    try { persist(session) } catch (error) { failed.value = true; options.error(error) }
    // File uploads start immediately, independently of the text throttle.
    if (descriptors.some(item => !item.uploaded)) void flush(session).catch(error => reportFor(session, error))
  }
  function report(error: unknown): void {
    if (isAxiosError(error) && error.response?.status === 409) conflicted.value = true
    if (!failed.value) options.error(error)
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
  async function flush(session: Session): Promise<void> {
    if (session.paused) return
    if (session.running) { await session.running; if (session.record.dirty) return flush(session); return }
    session.running = (async () => {
      await session.initialized
      if (session.generation !== sessionGeneration() || (!session.record.dirty && !session.removed.size)) return
      if (current === session) saving.value = true
      try {
        async function cleanup(): Promise<void> {
          for (const key of session.removed) {
            if (session.generation !== sessionGeneration()) return
            await chatService.discardDraftFile(session.room, key)
            session.removed.delete(key)
            session.record.removedKeys = [...session.removed]
            persist(session)
          }
        }
        async function push(sent: { revision: number; mutationKey: string; content: DraftContent | null }): Promise<void> {
          if (session.generation !== sessionGeneration()) return
          session.record.pending = sent
          persist(session)
          const saved = await chatService.saveDraft(session.room, sent.revision, sent.mutationKey, sent.content)
          if (session.generation !== sessionGeneration()) return
          session.record.revision = saved.revision
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
          if (session.generation !== sessionGeneration()) return
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
  watch([options.room, () => auth.user?.id], ([room, user]) => {
    if (current) leave(current)
    current = null
    ready.value = false
    failed.value = false
    conflicted.value = false
    if (!user) return
    const key = draftKey(user, room)
    let local: LocalDraft | null = null
    try { local = readLocalDraft(key) } catch (error) { report(error) }
    const session: Session = { room, key, generation: sessionGeneration(),
      record: local ?? { revision: 0, content: null, dirty: false, mutationKey: crypto.randomUUID() },
      blobs: new Map(), writes: [], running: null, initialized: Promise.resolve(), paused: false, removed: new Set(), owner: Symbol(key) }
    current = session
    session.removed = new Set(local?.removedKeys ?? [])
    localOwners.set(key, session.owner)
    apply(session.record.content, session)
    session.initialized = (async () => {
      try {
        for (const item of session.record.content?.files ?? []) {
          const file = await draftBlob(key, item.key)
          if (file) session.blobs.set(item.key, file)
        }
        const remote = await chatService.draft(room)
        if (session.generation !== sessionGeneration()) return
        if (!session.record.dirty) {
          session.record = { ...session.record, ...remote }
          persist(session)
          apply(remote.content, session)
        } else if (session.record.revision !== remote.revision) {
          conflicted.value = true
          throw new Error('Draft conflict: local changes preserved; server has a newer draft')
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
    if (session) void flush(session).catch(error => reportFor(session, error))
  }
  const timer = window.setInterval(wake, DRAFT_SYNC_MS)
  window.addEventListener('online', wake)
  window.addEventListener('pagehide', wake)
  document.addEventListener('visibilitychange', wake)
  onBeforeUnmount(() => {
    clearInterval(timer)
    window.removeEventListener('online', wake)
    window.removeEventListener('pagehide', wake)
    document.removeEventListener('visibilitychange', wake)
    if (current) leave(current)
    current = null
  })
  async function prepare(): Promise<{ token: DraftSend; acknowledge: (accepted: boolean, clear: () => void) => Promise<void> } | undefined> {
    const session = current
    if (!session) return undefined
    // Fully drain edits occurring during an upload or autosave before publishing.
    do {
      if (current !== session || session.generation !== sessionGeneration()) throw new Error('Session changed')
      await flush(session)
    } while (session.record.dirty)
    if (current !== session || !session.record.content) throw new Error('Conversation changed')
    const sent = JSON.parse(JSON.stringify(session.record)) as LocalDraft
    const content = sent.content!
    session.paused = true
    return { token: { revision: sent.revision, clientMessageId: content.client_message_id, replyToMessageId: content.reply_to_message_id }, acknowledge: async (accepted, clear) => {
      session.paused = false
      if (!accepted) return
      // The server increments the cursor while clearing only this sent revision.
      if (session.record.revision === sent.revision) session.record.revision += 1
      if (session.record.mutationKey === sent.mutationKey) {
        session.record.content = null
        session.record.dirty = false
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
      for (const item of content.files) await draftBlob(session.key, item.key, null)
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
    conflicted.value = false
    failed.value = false
  }
  function cancelReply(): void { replyId.value = null; capture() }
  watch(options.reply, (value, previous) => { if (value !== previous) replyId.value = value })
  return { ready, saving, failed, conflicted, replyId, cancelReply, retry, prepare }
}
