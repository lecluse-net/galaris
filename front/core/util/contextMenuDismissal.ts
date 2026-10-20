import { useId, watch, type Ref } from 'vue'
import type { QMenu } from 'quasar'

/** A submenu is teleported, so its DOM is outside the root popup. */
function belongsToMenu(root: Element, target: EventTarget | null): boolean {
  if (!(target instanceof Node)) return false
  if (root.contains(target)) return true
  let popup = (target instanceof Element ? target : target.parentElement)?.closest<HTMLElement>('[data-context-submenu]') ?? null
  const seen = new Set<Element>()
  while (popup && !seen.has(popup)) {
    if (popup === root) return true
    seen.add(popup)
    popup = popup.dataset.contextParent ? document.getElementById(popup.dataset.contextParent) : null
  }
  return false
}

/** Close right-click menus even on their anchor, stopped events and embedded frames. */
export function useContextMenuDismissal(
  visible: Ref<boolean>,
  menu: () => QMenu | null,
  activator: () => Element | null | undefined = () => null,
): string {
  const id = `context-menu-${useId()}`
  watch(visible, (open, _, cleanup) => {
    if (!open) return
    function dismiss(event: Event): void {
      // Match Quasar's outside dismissal: preserve focus on the clicked control.
      menu()?.hide(Object.assign(event, { qClickOutside: true }))
    }
    function outside(event: Event): void {
      if (!visible.value) return
      const popup = menu()?.contentEl
      if (!popup) return
      const path = event.composedPath()
      if (path.some(target => belongsToMenu(popup, target))) return
      const button = activator()
      // The visible menu button keeps its ordinary toggle behaviour.
      if (button && path.some(target => target instanceof Node && button.contains(target))) return
      dismiss(event)
    }
    function blur(event: Event): void {
      // A click inside an iframe is delivered to its own document, not this one.
      queueMicrotask(() => {
        if (!visible.value) return
        const popup = menu()?.contentEl
        if (popup && belongsToMenu(popup, document.activeElement)) return
        dismiss(event)
      })
    }
    document.addEventListener('pointerdown', outside, true)
    document.addEventListener('click', outside, true)
    window.addEventListener('blur', blur)
    cleanup(() => {
      document.removeEventListener('pointerdown', outside, true)
      document.removeEventListener('click', outside, true)
      window.removeEventListener('blur', blur)
    })
  }, { flush: 'post' })
  return id
}
