<template>
  <q-field
    outlined
    dense
    stack-label
    hide-bottom-space
    :model-value="model"
    :label="t('documents.folder')"
    :disable="readonly"
    class="document-folder-select"
  >
    <template #control>
      <button
        type="button"
        class="document-folder-select__control"
        :disabled="readonly"
        @click="menuOpen = true"
      >
        <FolderIcon :tone="appearance(model).tone" :expanded="menuOpen" :title="t(appearance(model).label)" />
        <span class="ellipsis">{{ model || t('documents.folderRoot') }}</span>
      </button>
    </template>
    <template #append>
      <q-icon name="arrow_drop_down" class="cursor-pointer" @click="menuOpen = true" />
      <q-menu v-model="menuOpen" fit max-height="380px">
        <q-list class="document-folder-select__menu">
          <q-item clickable :active="!model" active-class="text-primary" @click="selectFolder('')">
            <q-item-section avatar><q-icon name="home" /></q-item-section>
            <q-item-section>{{ t('documents.folderRoot') }}</q-item-section>
            <q-item-section side>
              <q-btn
                flat
                round
                dense
                icon="add"
                :aria-label="t('documents.createSubfolderIn', { folder: t('documents.folderRoot') })"
                @click.stop="startCreate('')"
              />
            </q-item-section>
          </q-item>
          <q-separator />
          <q-tree
            v-if="folderNodes.length"
            v-model:expanded="expanded"
            :nodes="folderNodes"
            node-key="path"
            dense
            no-transition
            class="q-pa-sm"
          >
            <template #default-header="treeProps">
              <button
                type="button"
                class="document-folder-select__node"
                :class="{ 'text-primary': treeProps.node.path === model }"
                @click="selectFolder(treeProps.node.path)"
              >
                <FolderIcon :tone="appearance(treeProps.node.path).tone" :expanded="treeProps.expanded" :title="t(appearance(treeProps.node.path).label)" />
                <span class="ellipsis">{{ treeProps.node.label }}</span>
                <q-space />
                <q-btn
                  flat
                  round
                  dense
                  size="sm"
                  icon="add"
                  :aria-label="t('documents.createSubfolderIn', { folder: treeProps.node.path })"
                  @click.stop="startCreate(treeProps.node.path)"
                >
                  <q-tooltip>{{ t('documents.createSubfolder') }}</q-tooltip>
                </q-btn>
              </button>
            </template>
          </q-tree>
          <q-item v-else>
            <q-item-section class="text-grey-7">{{ t('documents.folderEmpty') }}</q-item-section>
          </q-item>
        </q-list>
      </q-menu>
    </template>
  </q-field>

  <q-dialog v-model="createOpen">
    <q-card class="document-folder-select__dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('documents.createSubfolder') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section>
        <div class="text-caption text-grey-7 q-mb-sm">
          {{ t('documents.folderParent', { folder: createParent || t('documents.folderRoot') }) }}
        </div>
        <q-input
          ref="folderNameInput"
          v-model="newFolderName"
          outlined
          autofocus
          :label="t('documents.folderName')"
          :rules="[folderNameRule]"
          @keyup.enter="createFolder"
        />
      </q-card-section>
      <q-separator />
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn v-close-popup flat :label="t('memory.cancel')" />
        <q-btn color="primary" :label="t('documents.createFolder')" @click="createFolder" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QInput } from 'quasar'
import { FolderIcon } from '@/core/util'
import { folderAppearance } from '../documentFolders'
import type { DocumentFolderOption } from '../types'

interface FolderNode {
  path: string
  label: string
  children: FolderNode[]
}

const { options, readonly = false } = defineProps<{
  options: DocumentFolderOption[]
  readonly?: boolean
}>()
const model = defineModel<string>({ required: true })
const { t, locale } = useI18n()
const menuOpen = ref(false)
const createOpen = ref(false)
const createParent = ref('')
const newFolderName = ref('')
const createdFolders = ref<string[]>([])
const expanded = ref<string[]>([])
const folderNameInput = useTemplateRef<QInput>('folderNameInput')

function normalizeFolder(value: string): string | null {
  const parts: string[] = []
  for (const rawPart of value.trim().replaceAll('\\', '/').split('/')) {
    const part = rawPart.trim()
    if (!part) continue
    if (part === '.' || part === '..') return null
    parts.push(part)
  }
  const path = parts.join('/')
  return path.length <= 500 ? path : null
}

const optionsByPath = computed(() => new Map(options.map(option => [option.path, option])))
const appearance = (path: string) => folderAppearance(optionsByPath.value.get(path))
const allFolders = computed(() => [...new Set([...options.map(option => option.path), ...createdFolders.value, model.value])]
  .map(normalizeFolder)
  .filter((value): value is string => Boolean(value))
  .sort((left, right) => left.localeCompare(right, locale.value, { sensitivity: 'base' })))

const folderNodes = computed<FolderNode[]>(() => {
  const roots: FolderNode[] = []
  const byPath = new Map<string, FolderNode>()
  for (const path of allFolders.value) {
    let parent = roots
    let currentPath = ''
    for (const label of path.split('/')) {
      currentPath = currentPath ? `${currentPath}/${label}` : label
      let node = byPath.get(currentPath)
      if (!node) {
        node = { path: currentPath, label, children: [] }
        byPath.set(currentPath, node)
        parent.push(node)
      }
      parent = node.children
    }
  }
  return roots
})

function selectFolder(path: string): void {
  model.value = path
  menuOpen.value = false
}

function startCreate(parent: string): void {
  createParent.value = parent
  newFolderName.value = ''
  createOpen.value = true
  void nextTick(() => folderNameInput.value?.focus())
}

const folderNameRule = (value: unknown): true | string => {
  const name = String(value ?? '').trim()
  return Boolean(name && !name.includes('/') && !name.includes('\\') && !['.', '..'].includes(name))
    || t('documents.folderNameInvalid')
}

function createFolder(): void {
  const name = newFolderName.value.trim()
  if (folderNameRule(name) !== true) return
  const path = normalizeFolder(createParent.value ? `${createParent.value}/${name}` : name)
  if (!path) return
  createdFolders.value = [...new Set([...createdFolders.value, path])]
  expanded.value = [...new Set([...expanded.value, ...path.split('/').map((_part, index, parts) => parts.slice(0, index + 1).join('/'))])]
  model.value = path
  createOpen.value = false
  menuOpen.value = false
}
</script>

<style scoped>
.document-folder-select__control,
.document-folder-select__node { display: flex; width: 100%; min-width: 0; align-items: center; gap: 8px; padding: 0; color: inherit; font: inherit; text-align: left; background: none; border: 0; cursor: pointer; }
.document-folder-select__control { height: 100%; }
.document-folder-select__control:disabled { cursor: default; }
.document-folder-select__menu { min-width: min(420px, 90vw); }
.document-folder-select__dialog { width: min(480px, 92vw); }
</style>
