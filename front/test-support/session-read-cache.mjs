import { loadTypescript } from './load-typescript.mjs'
import * as imageStorage from '../core/util/sessionImageStorage.ts'

export function sessionResources(api, cache, window) {
  return loadTypescript(new URL('../core/util/sessionResources.ts', import.meta.url), {
    '@/core/api': api, './sessionReadCache': cache, './previewQueue': cache, './sessionImageStorage': imageStorage,
  }, { window })
}

export function sessionReadCache(window = new EventTarget()) {
  const cache = loadTypescript(new URL('../core/util/sessionReadCache.ts', import.meta.url), {}, { window })
  return { ...cache,
    createSessionReadCache: options => cache.createSessionReadCache({ sessionEvent: 'auth', ...options }),
    createSessionResponseCache: options => cache.createSessionResponseCache({ sessionEvent: 'auth', ...options }),
    ...loadTypescript(new URL('../core/util/previewQueue.ts', import.meta.url), {}) }
}
