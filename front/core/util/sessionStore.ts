import { reactive, toRaw } from 'vue'
import type { Pinia, StateTree, StoreDefinition, StoreGeneric, _GettersTree } from 'pinia'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'

export interface StoreRequestState { pending: number; error: unknown }
const requests = new WeakMap<object, Record<string, StoreRequestState>>()
const requestVersions = new WeakMap<object, Map<string, symbol>>()

/** Per-action diagnostics; aggregate loading flags remain compatible with existing consumers. */
export function storeRequests(store: object): Readonly<Record<string, StoreRequestState>> {
  const identity = toRaw(store)
  let state = requests.get(identity)
  if (!state) { state = reactive({}); requests.set(identity, state) }
  return state
}

/** Capture at action entry when its existing contract absorbs a read failure. */
export function storeRequestFailure(store: object, action: string): (error: unknown) => void {
  // Pinia devtools wraps an action's `this` in another proxy in development.
  const identity = toRaw(store)
  const versions = requestVersions.get(identity), version = versions?.get(action)
  const operation = requests.get(identity)?.[action]
  return error => {
    if (version && operation && versions?.get(action) === version && requests.get(identity)?.[action] === operation) {
      operation.error = error
    }
  }
}

/** Opt-in for session-owned snapshots, never for editor buffers or application preferences. */
export function withSessionScope<Id extends string, S extends StateTree, G extends _GettersTree<S>, A>(
  definition: StoreDefinition<Id, S, G, A>,
  options: { flags?: Partial<Record<keyof A, string>>; reset?: (store: ReturnType<typeof definition>) => void } = {},
): StoreDefinition<Id, S, G, A> {
  const installed = new WeakSet<object>()
  const useStore = (pinia?: Pinia | null, hot?: StoreGeneric) => {
    const store = definition(pinia, hot)
    const identity = toRaw(store)
    if (installed.has(store)) return store
    installed.add(store)
    const state = storeRequests(store) as Record<string, StoreRequestState>
    const flags = options.flags as Readonly<Record<string, string>> | undefined
    const pending = new Map<symbol, { action: string; flag?: string }>()
    const latest = new Map<string, symbol>()
    requestVersions.set(identity, latest)
    let session = sessionGeneration()
    function updateFlags(): void {
      const active = new Set([...pending.values()].map(value => value.flag))
      for (const flag of new Set(Object.values(flags ?? {}))) (store as StoreGeneric)[flag] = active.has(flag)
    }
    function reset(): void {
      pending.clear()
      latest.clear()
      for (const action of Object.keys(state)) delete state[action]
      if (options.reset) options.reset(store)
      else store.$reset()
      updateFlags()
    }
    function sessionChanged(event?: Event): void {
      const next = sessionGeneration()
      if (next !== session || (event instanceof CustomEvent && event.detail === null)) {
        session = next
        reset()
      }
    }
    const unsubscribe = (store as StoreGeneric).$onAction(({ name, after, onError }) => {
      sessionChanged()
      // Synchronous query actions may run during rendering. Tracking them would
      // mutate a dependency of that render and cause a recursive update loop.
      if (!flags?.[name]) return
      const startedIn = session
      const key = Symbol(name), flag = flags?.[name]
      latest.set(name, key)
      state[name] ??= { pending: 0, error: null }
      const operation = state[name]!
      operation.pending++
      operation.error = null
      pending.set(key, { action: name, flag })
      function finish(error?: unknown): void {
        pending.delete(key)
        if (startedIn === session && state[name] === operation) {
          operation.pending--
          if (error !== undefined && latest.get(name) === key) operation.error = error
        } else if (error !== undefined && (store as StoreGeneric).error === error) {
          // HTTP rejects obsolete sessions before applying data. Its catch must
          // not replace the current session's diagnostics with that rejection.
          (store as StoreGeneric).error = null
        }
        updateFlags()
      }
      after(() => finish())
      onError(finish)
    }, true)
    window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged)
    window.addEventListener('storage', sessionChanged)
    const dispose = store.$dispose
    store.$dispose = () => {
      unsubscribe()
      pending.clear()
      window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged)
      window.removeEventListener('storage', sessionChanged)
      requests.delete(identity)
      requestVersions.delete(identity)
      dispose()
    }
    return store
  }
  return Object.assign(useStore, definition)
}
