<template>
  <q-btn-toggle v-if="modes.length > 1" dense unelevated no-caps color="primary" text-color="primary"
    toggle-color="primary" toggle-text-color="white" :model-value="mode" :options="options" :disable="busy"
    :aria-label="t('richEditor.resources.displayMode')" @update:model-value="emit('mode', $event)" />
  <slot />
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import type { DocumentReferenceMode } from '../documentReference'

const { mode, modes = [], busy = false } = defineProps<{ mode: DocumentReferenceMode; modes?: readonly DocumentReferenceMode[]; busy?: boolean }>()
const emit = defineEmits<{ mode: [mode: DocumentReferenceMode] }>()
const { t } = useI18n()
const $q = useQuasar()
const labels = { link: 'asUrl', card: 'asCard', embed: 'asEmbed' } as const
const icons = { link: 'link', card: 'view_agenda', embed: 'aspect_ratio' } as const
const options = computed(() => modes.map(value => ({ value, icon: icons[value], outline: mode !== value,
  label: $q.screen.lt.md ? undefined : t(`richEditor.resources.${value}`),
  attrs: { 'aria-label': t(`richEditor.resources.${labels[value]}`), title: t(`richEditor.resources.${value}`) },
})))
</script>
