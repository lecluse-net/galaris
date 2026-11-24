interface StoredImage {
  group: string
  scope: string
  key: string
  session: string
  version?: string
  blob: Blob
  savedAt: number
}

const storeName = 'images'
const maxEntries = 512
const maxBytes = 64 * 1024 * 1024
let database: Promise<IDBDatabase> | undefined

function openDatabase(): Promise<IDBDatabase> {
  database ??= new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open('galaris-session-images', 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore(storeName, { keyPath: ['scope', 'key'] })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
  return database
}

async function transaction<T>(
  mode: IDBTransactionMode, operation: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T | undefined> {
  try {
    const db = await openDatabase()
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(storeName, mode)
      tx.onabort = () => reject(tx.error)
      const request = operation(tx.objectStore(storeName))
      tx.oncomplete = () => resolve(request.result)
    })
  } catch {
    // The in-memory cache still works when storage is unavailable or full.
    return undefined
  }
}

export function readStoredImage(scope: string, key: string): Promise<StoredImage | undefined> {
  return transaction('readonly', store => store.get([scope, key]))
}

export async function discardStoredImage(image: StoredImage): Promise<void> {
  await transaction('readwrite', store => {
    const key = [image.scope, image.key]
    const request: IDBRequest<StoredImage | undefined> = store.get(key)
    request.onsuccess = () => {
      const current = request.result
      if (current?.session === image.session && current.version === image.version && current.savedAt === image.savedAt) {
        store.delete(key)
      }
    }
    return request
  })
}

export async function saveStoredImage(image: Omit<StoredImage, 'savedAt'>, isCurrent: () => boolean): Promise<void> {
  if (!image.blob.size || image.blob.size > maxBytes) return
  await transaction('readwrite', store => {
    const request: IDBRequest<StoredImage[]> = store.getAll()
    request.onsuccess = () => {
      if (!isCurrent()) return
      let bytes = image.blob.size
      let count = 1
      for (const entry of request.result.sort((a, b) => b.savedAt - a.savedAt)) {
        if (entry.scope === image.scope && entry.key === image.key) continue
        if (entry.session !== image.session || count >= maxEntries || bytes + entry.blob.size > maxBytes) {
          store.delete([entry.scope, entry.key])
        } else {
          count++
          bytes += entry.blob.size
        }
      }
      store.put({ ...image, savedAt: Date.now() })
    }
    return request
  })
}

export async function removeStoredImages(session: string, target?: { group: string; key: string }): Promise<void> {
  await transaction('readwrite', store => {
    const request: IDBRequest<StoredImage[]> = store.getAll()
    request.onsuccess = () => {
      for (const entry of request.result) {
        if (entry.session === session && (!target || (entry.group === target.group && entry.key === target.key))) {
          store.delete([entry.scope, entry.key])
        }
      }
    }
    return request
  })
}
