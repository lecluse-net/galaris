<template>
  <q-badge rounded :style="{ backgroundColor: solaireCss[color][$q.dark.isActive ? 'dark' : 'light'] }"
    :text-color="$q.dark.isActive ? 'white' : 'dark'" class="q-px-sm q-py-xs">
    {{ label }}
  </q-badge>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { solaireCss, type SolaireColor } from '@/core/util'

const props = defineProps<{ status: string }>()
const { t, te } = useI18n()
const states: Record<string, SolaireColor> = {
  success: 'green', completed: 'green', error: 'red', failed: 'red', running: 'blue',
  waiting: 'orange', cancelling: 'orange', queued: 'cyan', cancelled: 'gray',
}
const color = computed(() => states[props.status] ?? 'gray')
const label = computed(() => { const key = `processes.statuses.${props.status}`; return te(key) ? t(key) : props.status })
</script>
