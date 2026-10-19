import { onBeforeUnmount, onMounted, watch, type Ref } from 'vue'
import { websocket } from '@/core/websocket'

/** Only mounted run lists subscribe; bursts and slow responses require at most one follow-up. */
export function useProcessRunRefresh(reload: () => Promise<void>, loading: Ref<boolean>): void {
  let timer: ReturnType<typeof setTimeout> | undefined
  let running = false, pending = false, disposed = false

  function schedule(): void {
    if (disposed) return
    pending = true
    if (timer || running || loading.value || document.hidden) return
    timer = setTimeout(() => { timer = undefined; void refresh() }, 300)
  }

  async function refresh(): Promise<void> {
    if (disposed || document.hidden || loading.value) return
    pending = false
    running = true
    try { await reload() }
    finally {
      running = false
      if (pending) schedule()
    }
  }

  function visible(): void { if (!document.hidden) schedule() }
  watch(loading, value => { if (!value && pending) schedule() })

  onMounted(() => {
    websocket.createWebsocket()
    for (const action of ['create', 'update', 'delete']) websocket.onEvent('process_run', action, schedule)
    websocket.onConnect(schedule)
    document.addEventListener('visibilitychange', visible)
  })
  onBeforeUnmount(() => {
    disposed = true
    clearTimeout(timer)
    for (const action of ['create', 'update', 'delete']) websocket.offEvent('process_run', action, schedule)
    websocket.offConnect(schedule)
    document.removeEventListener('visibilitychange', visible)
  })
}
