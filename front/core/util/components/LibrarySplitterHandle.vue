<template>
  <span class="document-splitter-handle" :class="{ 'document-splitter-handle--horizontal': horizontal }"
    role="separator" :tabindex="disabled ? -1 : 0" :aria-disabled="disabled || undefined"
    :aria-orientation="horizontal ? 'horizontal' : 'vertical'" :aria-label="label"
    :aria-valuenow="position" :aria-valuemin="limits[0]" :aria-valuemax="limits[1]" @keydown="resize">
    <q-icon name="drag_indicator" size="16px" />
  </span>
</template>
<script setup lang="ts">
const position = defineModel<number>({ required: true })
const { horizontal, limits, step = 5, disabled } = defineProps<{
  horizontal?: boolean
  label: string
  limits: readonly [number, number]
  step?: number
  disabled?: boolean
}>()

function resize(event: KeyboardEvent): void {
  if (disabled) return
  const previous = horizontal ? 'ArrowUp' : 'ArrowLeft'
  const next = horizontal ? 'ArrowDown' : 'ArrowRight'
  const [min, max] = limits
  const value = event.key === 'Home' ? min
    : event.key === 'End' ? max
      : event.key === previous ? position.value - step
        : event.key === next ? position.value + step : null
  if (value === null) return
  event.preventDefault()
  event.stopPropagation()
  position.value = Math.min(max, Math.max(min, value))
}
</script>
<style scoped>
.document-splitter-handle { display: flex; width: 20px; height: 42px; align-items: center; justify-content: center; border: 1px solid color-mix(in srgb, currentColor 18%, transparent); border-radius: 10px; color: var(--solaire-gray-accent); background: var(--q-card-background, #fff); box-shadow: 0 2px 8px rgba(35, 46, 66, .12); }
.document-splitter-handle--horizontal { width: 42px; height: 20px; }
.document-splitter-handle--horizontal .q-icon { transform: rotate(90deg); }
.document-splitter-handle:hover, .document-splitter-handle:focus-visible { color: var(--solaire-blue-accent); }
.document-splitter-handle:focus-visible { outline: 2px solid var(--solaire-blue-accent); }
:global(body.body--dark .document-splitter-handle) { background: var(--q-dark-page); box-shadow: 0 2px 8px rgba(0, 0, 0, .38); }
</style>
