/** Background refreshes pause in hidden tabs and resume without overlapping requests. */
export function startVisiblePolling(
  refresh: () => void | Promise<unknown>,
  interval: number,
  visibility: Pick<Document, 'hidden' | 'addEventListener' | 'removeEventListener'> = document,
  onError: (error: unknown) => void = error => globalThis.reportError(error),
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined
  let stopped = false
  let running = false
  let refreshOnReturn = false
  const clear = (): void => { clearTimeout(timer); timer = undefined }
  const schedule = (): void => {
    if (!stopped && !visibility.hidden) timer = setTimeout(() => { void run() }, interval)
  }
  const run = async (): Promise<void> => {
    clear()
    if (stopped || visibility.hidden || running) return
    running = true
    refreshOnReturn = false
    try { await refresh() } catch (error) { onError(error) }
    finally {
      running = false
      if (!stopped && !visibility.hidden && refreshOnReturn) void run()
      else schedule()
    }
  }
  const changed = (): void => {
    clear()
    if (visibility.hidden || stopped) return
    if (running) refreshOnReturn = true
    else void run()
  }
  visibility.addEventListener('visibilitychange', changed)
  schedule()
  return () => {
    stopped = true
    clear()
    visibility.removeEventListener('visibilitychange', changed)
  }
}
