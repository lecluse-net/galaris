<template>
  <div class="document-tag-row row items-center no-wrap full-width" :class="{ 'document-tag-row--dark': $q.dark.isActive }" :draggable="!renaming && !busy">
    <q-btn flat dense round size="sm" class="folder-icon-button q-mr-xs" :aria-label="t('documents.library.changeIcon', { name: tag.name })" :disable="busy"
      @click="clickIcon" @keydown.f2.prevent.stop="startRename">
      <DocumentTagIcon :icon="tag.icon" :expanded="selected" size="26px" />
      <q-tooltip>{{ t(renaming ? 'documents.library.iconHint' : 'documents.library.renameHint') }}</q-tooltip>
      <DocumentTagIconPicker v-model="iconOpen" :busy="busy" :save="saveIcon" />
    </q-btn>
    <q-input v-if="renaming" v-model="name" autofocus dense outlined class="col" maxlength="100" :disable="busy"
      :aria-label="t('documents.library.name')" @click.stop @dblclick.stop @keydown.stop
      @keydown.enter.prevent="rename" @keydown.esc.prevent="finishRename" @blur="blurName" @focus="selectName">
      <template #append><q-btn flat dense round size="sm" icon="check" :aria-label="t('documents.library.save')" @mousedown.prevent @click.stop="rename" /></template>
    </q-input>
    <span v-else class="ellipsis col tag-name" tabindex="0" :title="tag.name"
      @keydown.f2.prevent.stop="startRename" @keydown.enter.prevent.stop="startRename">{{ tag.name }}</span>
    <div v-if="!renaming" class="tag-toolbar row items-center no-wrap" role="group" :aria-label="t('documents.library.tagActions', { name: tag.name })"
      @click.stop @dblclick.stop @dragstart.prevent.stop>
      <q-btn flat dense round size="sm" icon="playlist_add" :disable="busy" :aria-label="t('documents.library.newSibling', { name: tag.name })" @click="createSibling">
        <q-tooltip>{{ t('documents.library.newSibling', { name: tag.name }) }}</q-tooltip>
      </q-btn>
      <DocumentTagCreateButton :parent-id="tag.id" :parent-name="tag.name" :busy="busy" :save="create" />
      <q-btn flat dense round size="sm" icon="edit" :disable="busy" :aria-label="t('documents.library.editNamedTag', { name: tag.name })" @click="startRename">
        <q-tooltip>{{ t('documents.library.editTag') }}</q-tooltip>
      </q-btn>
      <q-btn flat dense round size="sm" icon="delete_outline" class="tag-delete" :disable="busy" :aria-label="t('documents.library.deleteNamedTag', { name: tag.name })" @click="emit('delete')">
        <q-tooltip>{{ t('documents.library.deleteTag') }}</q-tooltip>
      </q-btn>
      <q-btn flat dense round size="sm" icon="more_vert" :aria-label="t('documents.library.tagActions', { name: tag.name })">
        <q-tooltip>{{ t('documents.library.tagActions', { name: tag.name }) }}</q-tooltip>
        <q-menu>
          <q-list dense>
            <q-item v-close-popup clickable :disable="busy" @click="emit('sort', false)"><q-item-section avatar><q-icon name="sort_by_alpha" /></q-item-section><q-item-section>{{ t('documents.library.sortAscending') }}</q-item-section></q-item>
            <q-item v-close-popup clickable :disable="busy" @click="emit('sort', true)"><q-item-section avatar><q-icon name="sort_by_alpha" /></q-item-section><q-item-section>{{ t('documents.library.sortDescending') }}</q-item-section></q-item>
            <q-separator />
            <q-item v-close-popup clickable @click="emit('expand')"><q-item-section avatar><q-icon name="unfold_more" /></q-item-section><q-item-section>{{ t('documents.library.expandAll') }}</q-item-section></q-item>
            <q-item v-close-popup clickable @click="emit('collapse')"><q-item-section avatar><q-icon name="unfold_less" /></q-item-section><q-item-section>{{ t('documents.library.collapseAll') }}</q-item-section></q-item>
          </q-list>
        </q-menu>
      </q-btn>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DocumentTag } from '../types'
import DocumentTagCreateButton from './DocumentTagCreateButton.vue'
import DocumentTagIconPicker from './DocumentTagIconPicker.vue'
import DocumentTagIcon from './DocumentTagIcon.vue'
const props = defineProps<{
  tag: DocumentTag
  selected: boolean
  busy: boolean
  renameOnCreate?: boolean
  save: (tag: DocumentTag) => Promise<boolean>
  create: (name: string, parentId: string | null, afterTagId?: string) => Promise<boolean>
}>()
const emit = defineEmits<{ delete: []; renamed: []; sort: [descending: boolean]; expand: []; collapse: [] }>()
const { t } = useI18n()
const renaming = ref(false)
const name = ref('')
const iconOpen = ref(false)
async function createSibling(): Promise<void> {
  if (!props.busy) await props.create(t('documents.library.newFolderName'), props.tag.parent_id, props.tag.id)
}
function startRename(): void { if (!props.busy && !renaming.value) { name.value = props.tag.name; renaming.value = true } }
function finishRename(): void { iconOpen.value = false; renaming.value = false; emit('renamed') }
function clickIcon(event: Event): void {
  if (!renaming.value) return
  event.stopPropagation()
  iconOpen.value = true
}
async function saveIcon(icon: string | null): Promise<boolean> {
  if (props.busy) return false
  const saved = await props.save({ ...props.tag, name: name.value.trim() || props.tag.name, icon })
  if (saved) finishRename()
  return saved
}
function selectName(event: Event): void { if (event.target instanceof HTMLInputElement) event.target.select() }
function blurName(event: Event): void {
  if (iconOpen.value || (event instanceof FocusEvent && event.relatedTarget instanceof Element && event.relatedTarget.closest('.folder-icon-button'))) return
  void rename()
}
watch(() => props.renameOnCreate, value => { if (value) startRename() }, { immediate: true })
async function rename(): Promise<void> {
  if (!renaming.value || props.busy) return
  if (!name.value.trim() || name.value.trim() === props.tag.name) { finishRename(); return }
  if (await props.save({ ...props.tag, name: name.value.trim() })) finishRename()
}
</script>
<style scoped>
.document-tag-row { position: relative; min-width: 0; }
.tag-toolbar { position: absolute; right: 0; top: 50%; transform: translateY(-50%); border-radius: 4px; background: var(--solaire-gray-light); opacity: 0; pointer-events: none; }
.document-tag-row:hover .tag-toolbar, .document-tag-row:focus-within .tag-toolbar { opacity: 1; pointer-events: auto; }
.document-tag-row--dark .tag-toolbar { background: var(--solaire-gray-dark); }
.tag-delete { color: var(--solaire-red-accent); }
@media (hover: none), (max-width: 1023px) {
  .tag-toolbar { position: static; transform: none; opacity: 1; pointer-events: auto; }
}
.folder-icon-button { width: 26px; height: 26px; min-width: 26px; min-height: 26px; padding: 0; }
.tag-name { min-width: 0; cursor: pointer; }
.tag-name:focus-visible { outline: 2px solid var(--solaire-blue-accent); }
</style>
