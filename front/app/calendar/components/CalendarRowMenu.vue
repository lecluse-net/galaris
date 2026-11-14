<template>
  <ActionContextMenu :actions="actions" target=".calendar-choice" :label="label">
    <template #trigger="{ toggle, open }">
      <q-btn flat round dense color="primary" icon="more_vert" :aria-label="`${t('agenda.settings')} · ${label}`" aria-haspopup="menu" :aria-expanded="open" @click="toggle" />
    </template>
  </ActionContextMenu>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ActionContextMenu, useResourceCopy, type ContextAction } from '@/core/util'
const { id, label, visible, active = true, synchronizable = false } = defineProps<{
  id: number; label: string; visible: boolean; active?: boolean; synchronizable?: boolean
}>()
const emit = defineEmits<{ visibility: []; edit: []; sync: [] }>()
const { t } = useI18n(), resourceCopy = useResourceCopy()
const actions = computed<ContextAction[]>(() => [
  ...(id > 0 ? [resourceCopy.action(`galaris://calendar/${id}`)] : []),
  { key: 'visibility', label: t(visible ? 'agenda.hideCalendar' : 'agenda.showCalendar'), icon: visible ? 'visibility_off' : 'visibility', disabled: !active, run: () => emit('visibility') },
  { key: 'edit', label: t('agenda.settings'), icon: 'edit', run: () => emit('edit') },
  ...(synchronizable ? [{ key: 'sync', label: t('agenda.syncNow'), icon: 'sync', disabled: !active, run: () => emit('sync') }] : []),
])
</script>
