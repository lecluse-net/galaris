import { onScopeDispose, ref, type Ref } from 'vue'
import type { Team } from '../services/teamService'

export function useTeamOrdering(
  teams: Ref<Team[]>,
  enabled: Ref<boolean>,
  move: (id: number, target: number, after: boolean) => Promise<void>,
) {
  const dragged = ref<number | null>(null)
  const target = ref<{ id: number; after: boolean } | null>(null)
  let touchPointer: number | null = null

  function clear(): void {
    dragged.value = null
    target.value = null
    touchPointer = null
  }
  function over(event: DragEvent, id: number): void {
    if (!enabled.value || dragged.value === null || dragged.value === id) return
    event.preventDefault()
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
    const row = event.currentTarget as HTMLElement
    const rect = row.getBoundingClientRect()
    target.value = { id, after: event.clientY > rect.top + rect.height / 2 }
  }
  function start(event: DragEvent, id: number): void {
    if (!enabled.value) { event.preventDefault(); return }
    dragged.value = id
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move'
      event.dataTransfer.setData('text/plain', String(id))
      const row = (event.currentTarget as HTMLElement).closest<HTMLElement>('[data-team-id]')
      if (row) event.dataTransfer.setDragImage(row, 20, row.offsetHeight / 2)
    }
  }
  function drop(event: DragEvent, id: number): void {
    over(event, id)
    const source = dragged.value
    const destination = target.value
    clear()
    if (enabled.value && source !== null && destination && destination.id === id) {
      void move(source, id, destination.after)
    }
  }
  function pointerStart(event: PointerEvent, id: number): void {
    if (!enabled.value || event.pointerType === 'mouse') return
    touchPointer = event.pointerId
    dragged.value = id
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  }
  function pointerMove(event: PointerEvent): void {
    if (event.pointerId !== touchPointer || dragged.value === null) return
    const row = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('[data-team-id]')
    const id = Number(row?.dataset.teamId)
    if (!row || !id || id === dragged.value) { target.value = null; return }
    const rect = row.getBoundingClientRect()
    target.value = { id, after: event.clientY > rect.top + rect.height / 2 }
    if (event.clientY < 60) window.scrollBy(0, -20)
    if (event.clientY > window.innerHeight - 60) window.scrollBy(0, 20)
  }
  function pointerEnd(event: PointerEvent): void {
    if (event.pointerId !== touchPointer) return
    const source = dragged.value
    const destination = target.value
    clear()
    if (enabled.value && source !== null && destination) void move(source, destination.id, destination.after)
  }
  function keyboardMove(id: number, direction: -1 | 1): void {
    if (!enabled.value) return
    const next = teams.value[teams.value.findIndex(team => team.id === id) + direction]
    if (next) void move(id, next.id, direction === 1)
  }
  function rowClass(id: number): Record<string, boolean> {
    return {
      'team-dragging': dragged.value === id,
      'team-drop-before': target.value?.id === id && !target.value.after,
      'team-drop-after': target.value?.id === id && target.value.after,
    }
  }
  onScopeDispose(clear)
  return { start, over, drop, clear, pointerStart, pointerMove, pointerEnd, keyboardMove, rowClass }
}
