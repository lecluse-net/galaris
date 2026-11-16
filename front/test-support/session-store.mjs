import * as vue from 'vue'
import { loadTypescript } from './load-typescript.mjs'

export function sessionStoreScope(window = new EventTarget(), sessionGeneration = () => 'synthetic-session') {
  return loadTypescript(new URL('../core/util/sessionStore.ts', import.meta.url), {
    vue, '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'auth', sessionGeneration },
  }, { window })
}
