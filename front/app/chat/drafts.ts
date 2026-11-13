/** Private local recovery snapshots. Text commits synchronously; blobs use IndexedDB. */
export interface DraftFile { key: string; name: string; size: number; mime: string; uploaded: boolean }
export interface DraftContent {
  client_message_id: string
  text: string
  files: DraftFile[]
  resources: { uri: string; name: string }[]
  effort: number
  topic_id: string | null
  reply_to_message_id: string | null
}
export interface DraftSnapshot { revision: number; content: DraftContent | null }
export interface DraftSend { revision: number; clientMessageId: string; replyToMessageId?: string | null }
export interface LocalDraft extends DraftSnapshot {
  dirty: boolean
  mutationKey: string
  pending?: { revision: number; mutationKey: string; content: DraftContent | null }
  removedKeys?: string[]
}
export const DRAFT_SYNC_MS = 2_000
export const draftKey = (user: number, room: string): string => `galaris:chat-draft:v1:${user}:${room}`
export function readLocalDraft(key: string): LocalDraft | null {
  const raw = localStorage.getItem(key)
  return raw ? JSON.parse(raw) as LocalDraft : null
}
export function writeLocalDraft(key: string, value: LocalDraft): void {
  localStorage.setItem(key, JSON.stringify(value))
}
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('galaris-chat-drafts', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('files')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}
export async function draftBlob(scope: string, key: string, file?: File | null): Promise<File | undefined> {
  // Store portable bytes rather than a browser-owned File handle (Safari may
  // refuse to clone a file selected through its native picker).
  const value = file ? { bytes: await file.arrayBuffer(), name: file.name, type: file.type, lastModified: file.lastModified } : null
  const db = await database()
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('files', file === undefined ? 'readonly' : 'readwrite')
      const store = tx.objectStore('files')
      const id = `${scope}:${key}`
      const request = file === undefined ? store.get(id) : file === null ? store.delete(id) : store.put(value, id)
      tx.oncomplete = () => {
        const stored = request.result as { bytes: ArrayBuffer; name: string; type: string; lastModified: number } | undefined
        resolve(file === undefined && stored ? new File([stored.bytes], stored.name, { type: stored.type, lastModified: stored.lastModified }) : undefined)
      }
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error)
    })
  } finally { db.close() }
}
