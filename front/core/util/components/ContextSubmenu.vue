<template>
  <span ref="anchor" hidden />
  <q-menu ref="menu" v-bind="$attrs" v-model="open" :id="id" :target="trigger ?? false"
    no-parent-event no-refocus :no-focus="hoverOpened" :transition-duration="0"
    anchor="top end" self="top start" data-context-submenu="" :data-context-parent="parentId"
    @before-show="announce" @show="focusFirst" @pointerenter="cancelClose" @pointerleave="leave"
    @escape-key="queueRestore" @hide="finishHide" @keydown="menuKeydown">
    <slot />
  </q-menu>
</template>
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef, useId, useTemplateRef, watch } from 'vue'
import type { QMenu } from 'quasar'

defineOptions({ inheritAttrs: false })
const anchor = useTemplateRef('anchor'), menu = useTemplateRef<QMenu>('menu')
const id = `context-submenu-${useId()}`
const trigger = shallowRef<HTMLElement>(), open = ref(false), hoverOpened = ref(false)
const parentId = ref<string>()
let opening: ReturnType<typeof setTimeout> | undefined, closing: ReturnType<typeof setTimeout> | undefined
let disposed = false, request = 0
let restoreOnHide = false
let previous: Record<string, string | null> = {}

function cancelClose(): void { clearTimeout(closing); closing = undefined }
function cancelOpen(): void { clearTimeout(opening); opening = undefined }
function disabled(): boolean { return trigger.value?.getAttribute('aria-disabled') === 'true' || trigger.value?.hasAttribute('disabled') === true }
async function show(hover: boolean): Promise<void> {
  cancelOpen(); cancelClose()
  if (disabled()) return
  const ticket = ++request
  hoverOpened.value = hover
  await nextTick()
  if (disposed || ticket !== request || !trigger.value?.isConnected || disabled()) return
  menu.value?.show()
  if (!hover) {
    await nextTick()
    if (disposed || ticket !== request || !open.value) return
    focusFirst()
  }
}
function focusFirst(): void {
  if (hoverOpened.value || !open.value || disposed) return
  menu.value?.focus()
  document.getElementById(id)?.querySelector<HTMLElement>('[role^="menuitem"]:not([aria-disabled="true"]), .q-item[tabindex="0"]:not([aria-disabled="true"]), button:not([disabled]), [role="tab"][tabindex="0"]')?.focus({ preventScroll: true })
}
function hide(): void { request++; cancelOpen(); cancelClose(); menu.value?.hide() }
function enter(event: PointerEvent): void {
  if (event.pointerType === 'touch' || disabled()) return
  cancelClose(); cancelOpen()
  if (!open.value) opening = setTimeout(() => { void show(true) }, 100)
}
function inBranch(element: Element): boolean {
  let popup = element.closest<HTMLElement>('[data-context-submenu]')
  while (popup) {
    if (popup.id === id) return true
    popup = popup.dataset.contextParent ? document.getElementById(popup.dataset.contextParent) : null
  }
  return false
}
function leave(event: PointerEvent): void {
  if (event.pointerType === 'touch') return
  cancelOpen(); cancelClose()
  if (event.relatedTarget instanceof Element && inBranch(event.relatedTarget)) return
  closing = setTimeout(() => {
    if (trigger.value?.matches(':hover')) return
    // Child popups are teleported: DOM containment does not describe their menu branch.
    if ([...document.querySelectorAll('[data-context-submenu]:hover')].some(inBranch)) return
    hide()
  }, 220)
}
function click(event: MouseEvent): void {
  if (disabled()) return
  event.stopPropagation()
  void show(false)
}
function keydown(event: KeyboardEvent): void {
  if (!['Enter', ' ', 'ArrowRight'].includes(event.key) || disabled()) return
  event.preventDefault(); event.stopPropagation()
  void show(false)
}
function queueRestore(): void { restoreOnHide = true }
async function finishHide(): Promise<void> {
  if (!restoreOnHide) return
  restoreOnHide = false
  // Restore after Quasar releases the popup's focus guard.
  await nextTick()
  if (!disposed) trigger.value?.focus({ preventScroll: true })
}
function menuKeydown(event: KeyboardEvent): void {
  // A nested popup owns its own Left key; never close its ancestors as well.
  if (event.key !== 'ArrowLeft' || !(event.target instanceof Element) || event.target.closest('[data-context-submenu]')?.id !== id) return
  event.preventDefault(); event.stopPropagation(); queueRestore(); hide()
}
function announce(): void {
  document.dispatchEvent(new CustomEvent('galaris-submenu-open', { detail: { id, parent: trigger.value?.closest('.q-menu') } }))
}
function siblingOpened(event: Event): void {
  const detail = (event as CustomEvent<{ id: string; parent: Element | null }>).detail
  if (detail.id !== id && detail.parent === trigger.value?.closest('.q-menu')) hide()
}
watch(open, value => {
  trigger.value?.setAttribute('aria-expanded', String(value))
  if (!value) { request++; cancelOpen(); cancelClose() }
})
onMounted(() => {
  trigger.value = anchor.value?.parentElement ?? undefined
  if (!trigger.value) return
  parentId.value = trigger.value.closest('.q-menu')?.id
  previous = Object.fromEntries(['aria-haspopup', 'aria-expanded', 'aria-controls'].map(name => [name, trigger.value!.getAttribute(name)]))
  trigger.value.setAttribute('aria-haspopup', 'menu')
  trigger.value.setAttribute('aria-expanded', 'false')
  trigger.value.setAttribute('aria-controls', id)
  trigger.value.addEventListener('pointerenter', enter)
  trigger.value.addEventListener('pointerleave', leave)
  trigger.value.addEventListener('click', click)
  trigger.value.addEventListener('keydown', keydown)
  document.addEventListener('galaris-submenu-open', siblingOpened)
})
onBeforeUnmount(() => {
  disposed = true; request++; cancelOpen(); cancelClose()
  trigger.value?.removeEventListener('pointerenter', enter)
  trigger.value?.removeEventListener('pointerleave', leave)
  trigger.value?.removeEventListener('click', click)
  trigger.value?.removeEventListener('keydown', keydown)
  document.removeEventListener('galaris-submenu-open', siblingOpened)
  for (const [name, value] of Object.entries(previous)) {
    if (value === null) trigger.value?.removeAttribute(name)
    else trigger.value?.setAttribute(name, value)
  }
})
</script>
