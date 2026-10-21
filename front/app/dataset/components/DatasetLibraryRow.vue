<template>
  <div v-library-shortcuts="shortcuts" class="dataset-library-row row no-wrap items-center" tabindex="0"
    :class="{ 'dataset-library-row--compact': compact }" :draggable="!busy"
    @dragstart.stop="emit('drag', $event, item.id)" @dragend="emit('dragend')"
    @dragover.stop="emit('dragover', $event, item.id)" @drop.stop.prevent="emit('drop')">
    <q-item :to="`/dataset/${item.id}`" exact :active="item.id === selectedId" :dense="compact" class="dataset-link col" :aria-label="item.title" :aria-current="item.id === selectedId ? 'page' : undefined">
      <q-icon name="data_object" :size="compact ? '26px' : '22px'" class="dataset-icon" aria-hidden="true" />
      <span class="dataset-link-copy"><span class="dataset-link-title" :title="item.title">{{ item.title }}</span>
        <span v-if="!compact" class="text-caption text-grey-7"><time v-if="item.updated_at || item.created_at" :datetime="item.updated_at ?? item.created_at ?? undefined" :title="t('datasets.lastModified', { date: modified })">{{ modified }}</time> · {{ t('datasets.revision') }} {{ item.revision }}</span>
      </span>
    </q-item>
    <ActionContextMenu target=".dataset-library-row" :actions="actions" />
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { usePrivilegeStore } from '@/core/authorize'
import { ActionContextMenu, type ContextAction } from '@/core/util'
import { vLibraryShortcuts, type LibraryShortcuts } from '@/core/util'
import type { Dataset } from '../types'
const props = defineProps<{ item: Dataset; selectedId: string; busy: boolean; compact?: boolean }>()
const emit = defineEmits<{ action: [item: Dataset, action: 'rename' | 'delete' | 'move']; drag: [event: DragEvent, id: string]; dragend: []; dragover: [event: DragEvent, id: string]; drop: [] }>()
const { t, locale } = useI18n(), router = useRouter(), auth = usePrivilegeStore()
const modified = computed(() => { const date = props.item.updated_at ?? props.item.created_at; return date ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(date)) : '' })
const editable = computed(() => (auth.hasPrivilege('DATASET_EDIT') || auth.hasPrivilege('DATASET_ADMIN')) && props.item.can_write)
const shortcuts = computed<LibraryShortcuts>(() => props.busy ? {} : { F4: () => { void router.push(`/dataset/${props.item.id}`) },
  ...(editable.value ? { F2: () => emit('action', props.item, 'rename') } : {}),
  ...(editable.value && props.item.can_delete ? { Delete: () => emit('action', props.item, 'delete') } : {}) })
const actions = computed<ContextAction[]>(() => [
  { key: 'open', icon: 'visibility', label: t('common.open'), shortcut: 'F4', run: () => { void router.push(`/dataset/${props.item.id}`) } },
  { key: 'move', icon: 'drive_file_move', label: t('datasets.library.moveToTag'), disabled: props.busy, run: () => emit('action', props.item, 'move') },
  ...(editable.value ? [{ key: 'rename', icon: 'edit', label: t('datasets.library.renameTag'), shortcut: 'F2', disabled: props.busy, run: () => emit('action', props.item, 'rename') }] : []),
  ...(editable.value && props.item.can_delete ? [{ key: 'delete', icon: 'delete', label: t('datasets.delete'), shortcut: 'Delete', negative: true, disabled: props.busy, run: () => emit('action', props.item, 'delete') }] : []),
])
</script>
<style scoped>
.dataset-library-row { min-width: 0; }
.dataset-library-row[draggable='true'] { cursor: grab; }
.dataset-link { display: flex; align-items: center; gap: 10px; padding: 10px 8px; text-decoration: none; min-width: 0; }
.dataset-link:focus-visible { outline: 2px solid var(--solaire-blue-accent); }
.dataset-link-copy { display: flex; flex-direction: column; min-width: 0; }
.dataset-link-title { overflow-wrap: anywhere; font-weight: 500; }
.dataset-icon { flex-shrink: 0; color: var(--solaire-gray-accent); }
.dataset-library-row--compact .dataset-link { min-height: 26px; gap: 4px; padding: 0; }
.dataset-library-row--compact .dataset-link-copy { display: block; overflow: hidden; }
.dataset-library-row--compact .dataset-link-title { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 400; }
</style>
