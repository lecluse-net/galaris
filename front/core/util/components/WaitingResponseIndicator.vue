<template>
  <span
    class="waiting-response-indicator row inline items-center justify-center"
    role="status"
    aria-live="polite"
    :aria-label="label"
  >
    <q-spinner-dots :color="color" :size="size" aria-hidden="true" />
    <q-tooltip>{{ label }}</q-tooltip>
  </span>
</template>

<script setup lang="ts">
const {
  label,
  color = 'primary',
  size = '24px',
} = defineProps<{
  label: string
  color?: string
  size?: string
}>()
</script>

<style scoped>
.waiting-response-indicator {
  min-height: 1.5em;
  vertical-align: middle;
}
</style>
