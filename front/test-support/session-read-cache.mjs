import { loadTypescript } from './load-typescript.mjs'

export function sessionReadCache(window = new EventTarget()) {
  const cache = loadTypescript(new URL('../core/util/sessionReadCache.ts', import.meta.url), {}, { window })
  return { ...cache,
    createSessionReadCache: options => cache.createSessionReadCache({ sessionEvent: 'auth', ...options }),
    createSessionResponseCache: options => cache.createSessionResponseCache({ sessionEvent: 'auth', ...options }),
    ...loadTypescript(new URL('../core/util/previewQueue.ts', import.meta.url), {}) }
}
