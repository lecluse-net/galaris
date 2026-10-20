<template>
  <q-card flat bordered class="metric-card full-height" :class="{ 'metric-card--interactive': interactive, 'metric-card--active': active }"
    :style="style" :role="interactive ? 'button' : undefined" :tabindex="interactive ? 0 : undefined"
    :aria-pressed="interactive ? active : undefined" :aria-busy="loading || undefined"
    @click="activate" @keydown="onKeydown">
    <q-card-section class="metric-card-body row items-center no-wrap">
      <q-avatar class="metric-card-icon" :icon="icon" aria-hidden="true" />
      <div class="metric-card-content col">
        <div class="text-caption text-grey-7 ellipsis">{{ label }}</div>
        <q-skeleton v-if="loading" type="text" width="48px" height="32px" />
        <div v-else class="text-h5 text-weight-medium">{{ value }}</div>
      </div>
    </q-card-section>
    <slot />
  </q-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { solaireCss, type SolaireColor } from '../solaire'
import '../solaireTheme'

const { tone = 'blue', interactive = false, active = false, loading = false } = defineProps<{
  label: string; value: string | number; icon: string; tone?: SolaireColor
  interactive?: boolean; active?: boolean; loading?: boolean
}>()
const emit = defineEmits<{ activate: [] }>()
const style = computed(() => ({
  '--metric-accent': solaireCss[tone].accent,
  '--metric-light': solaireCss[tone].light,
  '--metric-dark': solaireCss[tone].dark,
}))

function activate(): void { if (interactive) emit('activate') }
function onKeydown(event: KeyboardEvent): void {
  if (!interactive || event.target !== event.currentTarget || !['Enter', ' '].includes(event.key)) return
  event.preventDefault()
  activate()
}
</script>

<style scoped>
.metric-card { transition: border-color 160ms ease; }
.metric-card--interactive { cursor: pointer; }
.metric-card--interactive:hover, .metric-card--active { border-color: var(--metric-accent); }
.metric-card--interactive:focus-visible { outline: 2px solid var(--metric-accent); outline-offset: 2px; }
.metric-card-icon { color: var(--metric-accent); background: var(--metric-light); }
.metric-card-content { min-width: 0; margin-left: 16px; }
body.body--dark .metric-card-icon { background: var(--metric-dark); }
@media (max-width: 599px) {
  .metric-card-body { padding: 12px; }
  .metric-card-icon { font-size: 36px; }
  .metric-card-content { margin-left: 8px; }
}
</style>
