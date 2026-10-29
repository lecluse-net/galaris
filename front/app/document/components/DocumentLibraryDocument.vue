<template>
  <div>
    <div v-library-shortcuts="shortcuts" class="document-branch-row row no-wrap items-center" :title="t('documents.shortcuts.document')" aria-keyshortcuts="F2 F3 F4 F7 Delete" :class="[dropClass, { 'document-branch-row--compact': compact }]"
      @dragover.stop="emit('dragover', $event, entry, parentDocumentId, tagId, listOnly)"
      @dragleave.stop="emit('dragleave')" @drop.prevent.stop="emit('drop')">
      <DocumentLibraryEntryRow class="col" :entry="entry" :loading="false" :compact="compact" :selected-document-id="selectedDocumentId"
        @select="emit('select', $event)" @dragstart="(event, id) => emit('dragstart', event, id)" @dragend="emit('dragend')">
        <template #toggle>
          <span v-if="!treeRow" class="document-branch-toggle-slot">
            <button v-if="hasChildren" type="button" class="document-branch-toggle"
              :aria-label="t(open ? 'documents.library.collapseDocument' : 'documents.library.expandDocument', { name: entry.item.title })"
              :aria-expanded="open" :aria-busy="Boolean(loading[branchKey])" :disabled="loading[branchKey]" @click.stop="emit('toggle', entry.item.id)"
              @keydown.enter.stop @keydown.space.stop>
              <q-spinner v-if="loading[branchKey]" size="16px" />
              <q-icon v-else :name="$q.iconSet.tree.icon" class="q-tree__arrow" :class="{ 'q-tree__arrow--rotate': open }" />
            </button>
          </span>
        </template>
      </DocumentLibraryEntryRow>
      <div v-if="treeRow" class="document-actions row no-wrap items-center">
        <q-btn flat round dense size="sm" icon="note_add" :disable="busy" :aria-label="t('documents.library.newSubdocument', { name: entry.item.title })"
          @click.stop="emit('create', entry, undefined, $event)">
          <q-tooltip>{{ t('documents.library.newSubdocument', { name: entry.item.title }) }}</q-tooltip>
        </q-btn>
      </div>
      <DocumentRowMenu :entry="entry" :busy="busy" target=".document-branch-row" @select="emit('select', entry)" @create="type => emit('create', entry, type)" @action="emit('action', entry, $event)" />
    </div>
    <div v-if="open && !treeRow" class="document-children" :aria-label="t('documents.library.subdocuments', { name: entry.item.title })" @click.stop>
      <q-banner v-if="errors[branchKey]" dense role="alert">{{ t('documents.loadError') }}
        <q-btn flat dense :label="t('documents.retry')" @click="emit('retry', entry.item.id)" />
      </q-banner>
      <DocumentLibraryDocument v-for="child in visibleChildren" :key="child.item.id" :entry="child" :parent-document-id="entry.item.id" :ancestors="[...(ancestors ?? []), entry.item.id]"
        :compact="true" :selected-document-id="selectedDocumentId" :busy="busy" :children="children" :loading="loading" :errors="errors"
        :expanded="expanded" :drop-target="dropTarget" :drop-placement="dropPlacement"
        @select="emit('select', $event)" @create="(entry, type, event) => emit('create', entry, type, event)" @action="(entry, action) => emit('action', entry, action)"
        @toggle="emit('toggle', $event)" @retry="emit('retry', $event)" @dragstart="(event, id) => emit('dragstart', event, id)" @dragend="emit('dragend')"
        @dragover="(event, value, parent, tag, list) => emit('dragover', event, value, parent, tag, list)" @dragleave="emit('dragleave')" @drop="emit('drop')" />
      <span v-if="!loading[branchKey] && !errors[branchKey] && !(children[branchKey]?.length)" class="text-caption q-pa-sm">{{ t('documents.library.noSubdocuments') }}</span>
    </div>
  </div>
</template>
<script setup lang="ts">
import type { DocumentKind } from '../documentTypes'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DocumentLibraryEntry } from '../types'
import DocumentLibraryEntryRow from '@/app/document/components/DocumentLibraryEntryRow.vue'
import DocumentRowMenu from '@/app/document/components/DocumentRowMenu.vue'
import { documentRowShortcuts, vLibraryShortcuts, type DocumentRowAction } from '@/app/document/libraryShortcuts'

const props = defineProps<{
  entry: DocumentLibraryEntry
  selectedDocumentId: string | null
  compact?: boolean
  treeRow?: boolean
  ancestors?: string[]
  busy: boolean
  tagId?: string | null
  parentDocumentId?: string | null
  listOnly?: boolean
  children: Record<string, DocumentLibraryEntry[]>
  loading: Record<string, boolean>
  errors: Record<string, boolean>
  expanded: string[]
  dropTarget: string | null
  dropPlacement: string
}>()
const emit = defineEmits<{
  action: [entry: DocumentLibraryEntry, action: DocumentRowAction]
  select: [entry: DocumentLibraryEntry]; create: [entry: DocumentLibraryEntry, type?: DocumentKind, event?: Event]
  toggle: [id: string]; retry: [id: string]; dragstart: [event: DragEvent, id: string]; dragend: []
  dragover: [event: DragEvent, entry: DocumentLibraryEntry, parent?: string | null, tag?: string | null, listOnly?: boolean]
  dragleave: []; drop: []
}>()
const { t } = useI18n()
const shortcuts = computed(() => documentRowShortcuts(props.entry, props.busy,
  () => emit('select', props.entry), () => emit('create', props.entry), action => emit('action', props.entry, action)))
const branchKey = computed(() => `doc:${props.entry.item.id}`)
const visibleChildren = computed(() => (props.children[branchKey.value] ?? []).filter(child =>
  child.item.id !== props.entry.item.id && !props.ancestors?.includes(child.item.id)))
const open = computed(() => props.expanded.includes(branchKey.value))
const hasChildren = computed(() => open.value || Boolean(props.entry.children_count) || Boolean(props.children[branchKey.value]?.length))
const dropClass = computed(() => props.dropTarget === `doc:${props.entry.item.id}` ? {
  'tag-row--drop': props.dropPlacement === 'inside', 'node-drop-before': props.dropPlacement === 'before', 'node-drop-after': props.dropPlacement === 'after',
} : {})
</script>
<style scoped>
.document-branch-row { min-width: 0; }
.document-branch-toggle-slot { display: inline-flex; align-items: center; flex: 0 0 17px; align-self: flex-start; height: 28px; }
.document-branch-row--compact .document-branch-toggle-slot { height: 26px; }
.document-branch-row--compact :deep(> .q-item) { padding-inline: 0; }
.document-actions { flex: 0 0 24px; }
.document-actions > :deep(.q-btn) { flex: 0 0 24px; width: 24px; min-width: 24px; }
.document-branch-toggle { display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; width: 16px; height: 16px; margin: 0 1px 0 0; padding: 0; border: 0; background: transparent; color: var(--solaire-gray-accent); cursor: pointer; }
.document-branch-toggle :deep(.q-tree__arrow) { font-size: 16px; margin: 0; }
.document-branch-toggle:focus-visible { outline: 2px solid var(--solaire-blue-accent); outline-offset: 2px; }
.document-children { margin-inline-start: 16px; border-inline-start: 1px solid var(--solaire-gray-accent); }
.tag-row--drop { background: var(--solaire-blue-light); }
:global(body.body--dark) .tag-row--drop { background: var(--solaire-blue-dark); }
.node-drop-before { box-shadow: inset 0 2px var(--solaire-blue-accent); }
.node-drop-after { box-shadow: inset 0 -2px var(--solaire-blue-accent); }
</style>
