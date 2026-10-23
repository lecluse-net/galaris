<template>
  <div v-library-shortcuts="shortcuts" class="document-tag-row row items-center no-wrap full-width" :title="t('documents.shortcuts.folder')" aria-keyshortcuts="F2 F3 F4 F7 Delete" :draggable="!renaming && !busy" @contextmenu.stop="openPointerMenu" @keydown="openKeyboardMenu">
    <q-btn flat dense round size="sm" class="folder-icon-button q-mr-xs" :aria-label="t('documents.library.changeIcon', { name: tag.name })" :disable="busy"
      @click="clickIcon">
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
      @keydown.enter.prevent.stop="startRename">{{ tag.name }}</span>
    <div v-if="!renaming" class="tag-actions row items-center no-wrap" @click.stop @dblclick.stop @dragstart.prevent.stop>
      <q-btn flat dense round size="sm" icon="note_add" :disable="busy" :aria-label="t('documents.library.newDocument', { name: tag.name })" @click="emit('createDocument')">
        <q-tooltip>{{ t('documents.library.newDocument', { name: tag.name }) }}</q-tooltip>
      </q-btn>
      <q-btn flat dense round size="sm" icon="create_new_folder" :disable="busy" :aria-label="t('documents.library.newSubtag', { name: tag.name })" @click="createChild">
        <q-tooltip>{{ t('documents.library.newSubtag', { name: tag.name }) }}</q-tooltip>
      </q-btn>
      <q-btn flat dense round size="sm" icon="edit" :disable="busy" :aria-label="t('documents.library.editNamedTag', { name: tag.name })" @click="startRename">
        <q-tooltip>{{ t('documents.library.editTag') }}</q-tooltip>
      </q-btn>
      <q-btn flat dense round size="sm" icon="delete_outline" class="tag-delete" :disable="busy" :aria-label="t('documents.library.deleteNamedTag', { name: tag.name })" @click="emit('delete')">
        <q-tooltip>{{ t('documents.library.deleteTag') }}</q-tooltip>
      </q-btn>
    </div>
    <q-menu v-if="!renaming" :id="menuId" ref="contextMenu" v-model="menuOpen" no-parent-event touch-position class="tag-context-menu" role="menu" :aria-label="t('documents.library.tagActions', { name: tag.name })">
      <q-list dense>
        <template v-for="action in contextActions" :key="action.key">
          <q-separator v-if="action.separator" />
          <q-item v-close-popup clickable role="menuitem" :aria-label="action.label" :disable="action.disabled" :class="{ 'tag-delete': action.negative }" @click="action.run()">
            <q-item-section avatar><q-icon :name="action.icon" :class="{ 'tag-action-icon': !action.negative }" /></q-item-section>
            <q-item-section>{{ action.label }}</q-item-section>
            <q-item-section v-if="action.shortcut" side>{{ action.shortcut }}</q-item-section>
          </q-item>
        </template>
      </q-list>
    </q-menu>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QMenu } from 'quasar'
import { useContextMenuDismissal } from '@/core/util'
import type { DocumentTag } from '../types'
import { vLibraryShortcuts, type LibraryShortcuts } from '@/app/document/libraryShortcuts'
import DocumentTagIconPicker from '@/app/document/components/DocumentTagIconPicker.vue'
import DocumentTagIcon from '@/app/document/components/DocumentTagIcon.vue'
const props = defineProps<{
  tag: DocumentTag
  selected: boolean
  busy: boolean
  renameOnCreate?: boolean
  save: (tag: DocumentTag) => Promise<boolean>
  create: (name: string, parentId: string | null, afterTagId?: string) => Promise<boolean>
}>()
const emit = defineEmits<{ browse: []; createDocument: []; delete: []; confirmDelete: []; renamed: []; sort: [descending: boolean]; expand: []; collapse: [] }>()
const { t } = useI18n()
const renaming = ref(false)
const name = ref('')
const iconOpen = ref(false)
const menuOpen = ref(false)
const contextMenu = useTemplateRef<QMenu>('contextMenu')
const menuId = useContextMenuDismissal(menuOpen, () => contextMenu.value)
function openPointerMenu(event: MouseEvent): void {
  if (renaming.value) return
  event.preventDefault()
  contextMenu.value?.show(event)
}
const shortcuts = computed<LibraryShortcuts>(() => props.busy || renaming.value ? {} : {
  F2: startRename, F3: () => emit('createDocument'), F4: () => emit('browse'), F7: () => { void createChild() }, Delete: () => emit('confirmDelete'),
})
const contextActions = computed(() => [
  { key: 'browse', icon: 'view_list', label: t('documents.library.openFolderAction'), shortcut: 'F4', run: () => emit('browse') },
  { key: 'document', icon: 'note_add', label: t('documents.library.newDocumentAction'), shortcut: 'F3', disabled: props.busy, run: () => emit('createDocument') },
  { key: 'child', icon: 'create_new_folder', label: t('documents.library.newSubtagAction'), shortcut: 'F7', disabled: props.busy, run: createChild },
  { key: 'sibling', icon: 'playlist_add', label: t('documents.library.newSiblingAction'), disabled: props.busy, run: createSibling },
  { key: 'edit', icon: 'edit', label: t('documents.library.editTag'), shortcut: 'F2', disabled: props.busy, run: startRename },
  { key: 'ascending', icon: 'sort_by_alpha', label: t('documents.library.sortAscending'), disabled: props.busy, separator: true, run: () => emit('sort', false) },
  { key: 'descending', icon: 'sort_by_alpha', label: t('documents.library.sortDescending'), disabled: props.busy, run: () => emit('sort', true) },
  { key: 'expand', icon: 'unfold_more', label: t('documents.library.expandAll'), separator: true, run: () => emit('expand') },
  { key: 'collapse', icon: 'unfold_less', label: t('documents.library.collapseAll'), run: () => emit('collapse') },
  { key: 'delete', icon: 'delete_outline', label: t('documents.library.deleteTag'), shortcut: t('documents.shortcuts.deleteKey'), disabled: props.busy, separator: true, negative: true, run: () => emit('delete') },
])
function openKeyboardMenu(event: KeyboardEvent): void {
  if (renaming.value || !(event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10'))) return
  event.preventDefault()
  event.stopPropagation()
  contextMenu.value?.show()
}
async function createChild(): Promise<void> {
  if (!props.busy) await props.create(t('documents.library.newFolderName'), props.tag.id)
}
async function createSibling(): Promise<void> {
  if (!props.busy) await props.create(t('documents.library.newFolderName'), props.tag.parent_id, props.tag.id)
}
function startRename(): void { if (!props.busy && !renaming.value) { menuOpen.value = false; name.value = props.tag.name; renaming.value = true } }
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
.tag-actions { flex-shrink: 0; }
.tag-delete { color: var(--solaire-red-accent); }
.tag-action-icon { color: var(--solaire-gray-accent); }
.tag-context-menu { max-width: calc(100vw - 16px); }
.folder-icon-button { width: 26px; height: 26px; min-width: 26px; min-height: 26px; padding: 0; }
.tag-name { min-width: 0; cursor: pointer; }
.tag-name:focus-visible { outline: 2px solid var(--solaire-blue-accent); }
</style>
