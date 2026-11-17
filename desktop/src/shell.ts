import { tabBarHeight } from './layout.ts'

export const shellMessage = 'galaris-desktop-layout:'
export interface ShellLayout { integrated: boolean; left: number; dark: boolean; surface: string; ratio: number }

/** Presentation only. Remote pages cannot invoke desktop commands through this channel. */
export function readShellLayout(message: string): ShellLayout | undefined {
  if (!message.startsWith(shellMessage) || message.length > 512) return
  try {
    const value: unknown = JSON.parse(message.slice(shellMessage.length))
    if (!value || typeof value !== 'object') return
    const entry = value as Record<string, unknown>
    if (typeof entry.integrated !== 'boolean' || typeof entry.dark !== 'boolean'
      || typeof entry.left !== 'number' || !Number.isFinite(entry.left) || entry.left < 0
      || typeof entry.ratio !== 'number' || !Number.isFinite(entry.ratio) || entry.ratio <= 0
      || typeof entry.surface !== 'string' || !/^rgb\(\d{1,3}, \d{1,3}, \d{1,3}\)$/.test(entry.surface)) return
    return { integrated: entry.integrated, left: entry.left, dark: entry.dark, surface: entry.surface, ratio: entry.ratio }
  } catch { return }
}

/** Runs in an isolated world, without Node, a preload, or a privileged remote API. */
function observeShell(height: number, prefix: string): void {
  let container: HTMLElement | null = null
  let previous = ''
  let frame = 0
  const style = document.createElement('style')
  style.textContent = `
    :root[data-galaris-desktop-shell] .page-container { padding-top: ${height}px !important; }
    :root[data-galaris-desktop-shell] .page-container .user-btn-top-right { top: ${height + 12}px; }
    :root[data-galaris-desktop-shell] .page-container .q-page:not(.messenger-page) { min-height: calc(100vh - ${height + 50}px) !important; }
    :root[data-galaris-desktop-shell] .page-container:has(> .viewport-page--desktop) > .viewport-page--desktop { min-height: 0 !important; }
    :root[data-galaris-desktop-shell] .page-container .messenger-page { height: calc(100dvh - ${height}px) !important; min-height: 0 !important; }
    :root[data-galaris-desktop-shell] .q-dialog__inner--maximized { top: ${height}px; }
  `
  document.head.append(style)
  const resize = new ResizeObserver(() => schedule())
  function update(): void {
    frame = 0
    const next = document.querySelector<HTMLElement>('.page-container')
    if (next !== container) {
      resize.disconnect()
      container = next
      if (container) resize.observe(container)
    }
    const integrated = Boolean(container && innerWidth >= 1024)
    document.documentElement.toggleAttribute('data-galaris-desktop-shell', integrated)
    const left = integrated && container ? parseFloat(getComputedStyle(container).paddingLeft) || 0 : 0
    const dark = document.body.classList.contains('body--dark')
    const candidates = [container?.querySelector('.q-page'), container, document.body]
    const surface = candidates.map(element => element && getComputedStyle(element).backgroundColor)
      .find(color => color && /^rgb\(/.test(color)) || (dark ? 'rgb(16, 16, 16)' : 'rgb(255, 255, 255)')
    const message = JSON.stringify({ integrated, left, dark, surface, ratio: devicePixelRatio })
    if (message !== previous) { previous = message; console.debug(prefix + message) }
  }
  function schedule(): void { if (!frame) frame = requestAnimationFrame(update) }
  new MutationObserver(records => { if (!container?.isConnected || records.some(record => record.target === container)) schedule() }).observe(document.body, { childList: true, subtree: true })
  new MutationObserver(schedule).observe(document.body, { attributes: true, attributeFilter: ['class', 'style'] })
  addEventListener('resize', schedule)
  addEventListener('pageshow', () => { if (container) resize.observe(container); previous = ''; schedule() })
  addEventListener('pagehide', () => { resize.disconnect(); cancelAnimationFrame(frame); frame = 0 }, { once: true })
  update()
}

export const shellScript = `(${observeShell.toString()})(${tabBarHeight},${JSON.stringify(shellMessage)})`
