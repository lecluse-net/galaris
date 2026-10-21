import { computed, nextTick, onScopeDispose, ref } from 'vue'
import { useRouter, type HistoryState } from 'vue-router'

interface BrowserNavigation {
  navigate: (id: string, position: number) => Promise<boolean>
  active: () => boolean
  href?: (id: string) => string
  leave?: () => Promise<boolean>
}

// Only the foreground document context handles browser traversal (including nested dialogs).
const contexts: {
  key: string
  active: () => boolean
  recording: () => boolean
  leave?: () => Promise<boolean>
  invalidateForwardPositions: (position: number) => void
}[] = []

export function useDocumentHistory(browser?: BrowserNavigation) {
  const router = useRouter()
  const browserPositions = new Map<number, number>()
  const context = {
    key: crypto.randomUUID(), active: () => Boolean(browser?.active()),
    recording: () => recording > 0, leave: browser?.leave,
    invalidateForwardPositions: (position: number) => {
      for (const [visit, browserPosition] of browserPositions) {
        if (browserPosition >= position) browserPositions.delete(visit)
      }
    },
  }
  let traversing = false
  let recording = 0
  let revision = 0
  const visits = ref<(string | null)[]>([])
  const position = ref(-1)
  const removeGuard = browser ? router.beforeEach(async (to, from) => {
    if (contexts.some(value => value.recording())) return
    const state = router.options.history.state.galarisDocuments
    let foreground = [...contexts].reverse().find(value => value.active())
    // Traversing beyond a dialog's first visit closes it before restoring its parent.
    while (foreground?.leave && (to.path !== from.path || !state || typeof state !== 'object' || Array.isArray(state) || typeof state[foreground.key] !== 'number')) {
      if (!await foreground.leave()) return false
      await nextTick()
      foreground = [...contexts].reverse().find(value => value.active())
    }
    if (foreground !== context || to.path !== from.path) return
    if (!state || typeof state !== 'object' || Array.isArray(state)) return
    const index = state[context.key]
    if (typeof index !== 'number' || index === position.value) return
    const id = visits.value[index]
    if (!id) return false
    const request = ++revision
    traversing = true
    try {
      const accepted = await browser.navigate(id, index)
      // Let Vue Router cancel superseded traversals without rolling back the newer one.
      if (request !== revision) return
      return accepted && position.value === index
    }
    finally { if (request === revision) traversing = false }
  }) : undefined
  onScopeDispose(() => {
    removeGuard?.()
    const index = contexts.indexOf(context)
    if (index !== -1) contexts.splice(index, 1)
  })
  function target(direction: -1 | 1): { id: string; position: number } | null {
    for (let index = position.value + direction; index >= 0 && index < visits.value.length; index += direction) {
      const id = visits.value[index]
      if (id) return { id, position: index }
    }
    return null
  }
  function record(id: string, index?: number): void {
    const previous = position.value
    if (index !== undefined) position.value = index
    else if (visits.value[position.value] !== id) {
      visits.value = [...visits.value.slice(0, position.value + 1), id]
      position.value = visits.value.length - 1
    }
    if (!browser || traversing || (previous === position.value && contexts.includes(context))) return
    if (!contexts.includes(context)) contexts.push(context)
    const state = router.options.history.state.galarisDocuments
    const markers: HistoryState = {}
    if (state && typeof state === 'object' && !Array.isArray(state)) {
      for (const owner of contexts) {
        if (typeof state[owner.key] === 'number') markers[owner.key] = state[owner.key]
      }
    }
    markers[context.key] = position.value
    const visit = position.value
    const request = revision
    const location = router.resolve(browser.href?.(id) ?? router.currentRoute.value.fullPath)
    const replace = previous === -1 || Boolean(browser.href && location.fullPath === router.currentRoute.value.fullPath)
    ++recording
    void router.push({
      path: location.path, query: location.query, hash: location.hash,
      force: true,
      replace,
      state: { galarisDocuments: markers },
    }).then(failure => {
      const browserPosition = router.options.history.state.position
      if (!failure && request === revision && typeof browserPosition === 'number') {
        // A new branch may discard another context's forward entries as well.
        if (!replace) for (const owner of contexts) owner.invalidateForwardPositions(browserPosition)
        browserPositions.set(visit, browserPosition)
      }
    }).finally(() => { --recording })
  }
  async function go(direction: -1 | 1): Promise<void> {
    const destination = target(direction)
    if (!destination || !browser) return
    const currentPosition = router.options.history.state.position
    const destinationPosition = browserPositions.get(destination.position)
    if (typeof currentPosition === 'number' && destinationPosition !== undefined && destinationPosition !== currentPosition) {
      await new Promise<void>(resolve => {
        const remove = router.afterEach(() => { remove(); resolve() })
        router.go(destinationPosition - currentPosition)
      })
    } else await browser.navigate(destination.id, destination.position)
  }
  function forget(id: string): void { visits.value = visits.value.map(value => value === id ? null : value) }
  function reset(): void {
    visits.value = []; position.value = -1; browserPositions.clear(); ++revision; traversing = false
    const index = contexts.indexOf(context)
    if (index !== -1) contexts.splice(index, 1)
    context.key = crypto.randomUUID()
  }
  return { target, record, go, forget, reset, canGoBack: computed(() => target(-1) !== null), canGoForward: computed(() => target(1) !== null) }
}
