<template>
  <div class="permission-control" role="group" :aria-label="control.label">
    <div v-if="showLabel" class="text-caption q-mb-xs">{{ control.label }}</div>
    <div ref="scroller" class="permission-toggle-scroll" tabindex="0">
      <q-btn-group flat class="permission-toggle">
        <q-btn v-for="option in options" :key="option.value" flat
          class="permission-choice" :class="{ 'permission-selected': option.value === control.value }"
          :style="permissionColorStyle(option.color)" :icon="option.icon"
          :aria-label="option.label" :aria-pressed="option.value === control.value"
          :disable="disabled || control.disabled || option.disable" @click="select(option.value)">
          <q-tooltip>{{ option.label }}</q-tooltip>
        </q-btn>
      </q-btn-group>
    </div>
    <div v-if="control.hint" class="text-caption text-grey-7 q-mt-xs">{{ control.hint }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, useTemplateRef, watch } from 'vue'
import type { PermissionControl } from '../services/permissionDashboard'
import { permissionChoiceAppearance, permissionColorStyle } from '../permissionPresentation'
const { control, disabled = false, showLabel = false } = defineProps<{ control: PermissionControl; disabled?: boolean; showLabel?: boolean }>()
const emit = defineEmits<{ change: [value: string] }>()
const options = computed(() => control.options.map(option => ({ ...option, ...permissionChoiceAppearance(control.id, option.value) })))
function select(value: string) {
  if (!disabled && !control.disabled && value !== control.value && control.options.some(option => option.value === value && !option.disable)) emit('change', value)
}
const scroller = useTemplateRef<HTMLDivElement>('scroller')
let observer: ResizeObserver | undefined
function revealSelection() {
  const container = scroller.value
  const selected = container?.querySelector<HTMLElement>('[aria-pressed="true"]')
  if (!container || !selected) return
  let left = 0, element: HTMLElement | null = selected
  while (element && element !== container) { left += element.offsetLeft; element = element.offsetParent as HTMLElement | null }
  if (element !== container) return
  const right = left + selected.offsetWidth
  if (left < container.scrollLeft || selected.offsetWidth > container.clientWidth) container.scrollLeft = left
  else if (right > container.scrollLeft + container.clientWidth) container.scrollLeft = right - container.clientWidth
}
watch(() => control.value, revealSelection, { flush: 'post' })
onMounted(() => { observer = new ResizeObserver(revealSelection); if (scroller.value) observer.observe(scroller.value) })
onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.permission-control { min-width: 0; max-width: 100%; }
.permission-toggle-scroll { position: relative; min-width: 0; max-width: 100%; overflow-x: auto; padding: 2px; }
.permission-toggle { flex-wrap: nowrap; width: max-content; }
.permission-choice { min-width: 40px; min-height: 40px; padding: 8px; color: var(--permission-accent); background: var(--permission-light); }
.permission-choice :deep(.q-icon) { font-size: 20px; }
.permission-selected { color: var(--permission-on-accent); background: var(--permission-accent); box-shadow: inset 0 -3px 0 rgba(0, 0, 0, .25); }
.permission-choice:focus-visible { outline: 2px solid var(--solaire-blue-accent); outline-offset: 2px; z-index: 1; }
body.body--dark .permission-choice:not(.permission-selected) { background: var(--permission-dark); }
</style>
