<template>
  <div ref="element" class="editorial-toolbar"
    :class="{
      'editorial-toolbars': sticky,
      'editorial-toolbar-simple': mode !== 'full',
      'editorial-toolbar-inline': mode === 'inline',
    }"
    role="toolbar" :aria-label="label" @keydown="navigate" @mousedown="onMouseDown">
    <DocumentToolbarNavigation v-if="documentNavigation && registerToolbar" :fullscreen-exit="fullscreenExit" />
    <slot />
  </div>
</template>

<script setup lang="ts">
import { inject, useTemplateRef, watch } from 'vue'
import { registerDocumentFullscreenToolbarKey } from '../documentFullscreen'
import DocumentToolbarNavigation from './DocumentToolbarNavigation.vue'
import '../editorialTheme.css'

const { label, mode = 'full', sticky = false, preserveSelection = false, documentNavigation = false, fullscreenExit = false } = defineProps<{
  label: string
  mode?: 'full' | 'simple' | 'inline'
  sticky?: boolean
  preserveSelection?: boolean
  documentNavigation?: boolean
  fullscreenExit?: boolean
}>()
const registerToolbar = inject(registerDocumentFullscreenToolbarKey, null)
watch(() => documentNavigation, (enabled, _, cleanup) => {
  if (enabled && registerToolbar) cleanup(registerToolbar())
}, { immediate: true })
const element = useTemplateRef<HTMLElement>('element')
defineExpose({ element })

function onMouseDown(event: MouseEvent): void {
  if (preserveSelection) event.preventDefault()
}

function navigate(event: KeyboardEvent): void {
  if (event.defaultPrevented || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  const { target, currentTarget } = event
  if (!(target instanceof HTMLButtonElement) || !(currentTarget instanceof HTMLElement)
      || target.closest('[role="toolbar"]') !== currentTarget || target.getAttribute('aria-expanded') === 'true') return
  const buttons = [...currentTarget.querySelectorAll<HTMLButtonElement>('button:not([disabled])')]
    .filter(button => button.offsetParent !== null && button.closest('[role="toolbar"]') === currentTarget)
  const index = buttons.indexOf(target)
  if (index < 0) return
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
    : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length
  buttons[next]?.focus()
  event.preventDefault()
}
</script>
