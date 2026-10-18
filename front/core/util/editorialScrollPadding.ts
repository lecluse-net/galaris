interface Reservation {
  original: string
  priority: string
  baseline: string
  applied: string
  owners: Map<HTMLElement, number>
}
const reservations = new WeakMap<HTMLElement, Reservation>()

/** Native iframe scrolling must leave controls below the editor's sticky toolbar. */
export function reserveEditorialToolbarSpace(root: HTMLElement): { update: () => void; dispose: () => void } {
  let container: HTMLElement | undefined
  function release(): void {
    if (!container) return
    const reservation = reservations.get(container)
    if (reservation) {
      reservation.owners.delete(root)
      if (reservation.owners.size) apply(container, reservation)
      else {
        if (container.style.getPropertyValue('scroll-padding-top') === reservation.applied) {
          if (reservation.original) container.style.setProperty('scroll-padding-top', reservation.original, reservation.priority)
          else container.style.removeProperty('scroll-padding-top')
        }
        reservations.delete(container)
      }
    }
    container = undefined
  }
  function update(): void {
    const toolbar = root.querySelector<HTMLElement>('.editorial-toolbar')
    if (!root.isConnected || !toolbar) { release(); return }
    let target: HTMLElement | null = root
    while (target && !['auto', 'scroll', 'hidden', 'overlay'].includes(getComputedStyle(target).overflowY)) target = target.parentElement
    target ??= root.ownerDocument.scrollingElement as HTMLElement | null
    if (!target) { release(); return }
    if (target !== container) { release(); container = target }
    let reservation = reservations.get(target)
    if (!reservation) {
      const baseline = getComputedStyle(target).scrollPaddingTop
      reservation = { original: target.style.getPropertyValue('scroll-padding-top'), priority: target.style.getPropertyPriority('scroll-padding-top'),
        baseline: baseline === 'auto' ? '0px' : baseline, applied: '', owners: new Map() }
      reservations.set(target, reservation)
    }
    reservation.owners.set(root, toolbar.getBoundingClientRect().height + 8)
    apply(target, reservation)
  }
  return { update, dispose: release }
}

function apply(container: HTMLElement, reservation: Reservation): void {
  const height = Math.max(...reservation.owners.values())
  container.style.setProperty('scroll-padding-top', `max(${reservation.baseline}, ${height}px)`, reservation.priority)
  reservation.applied = container.style.getPropertyValue('scroll-padding-top')
}
