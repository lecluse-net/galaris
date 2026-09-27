// Optional previews share a small network budget, after the current render/scroll settles.
const pending: Array<() => void> = []
let running = 0
let timer: ReturnType<typeof setTimeout> | undefined

function schedule(): void {
  if (timer !== undefined || running >= 2 || pending.length === 0) return
  timer = setTimeout(() => {
    timer = undefined
    while (running < 2 && pending.length) pending.shift()?.()
  }, 100)
}

export function queuePreview<T>(load: () => Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const abort = (): void => {
      const index = pending.indexOf(start)
      if (index !== -1) pending.splice(index, 1)
      reject(new DOMException('Preview cancelled', 'AbortError'))
    }
    const start = (): void => {
      signal.removeEventListener('abort', abort)
      if (signal.aborted) { abort(); return }
      running++
      void Promise.resolve().then(load).then(resolve, reject).finally(() => {
        running--
        schedule()
      })
    }
    if (signal.aborted) { abort(); return }
    signal.addEventListener('abort', abort, { once: true })
    pending.push(start)
    schedule()
  })
}
