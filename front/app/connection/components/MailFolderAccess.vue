<template>
  <div class="mail-folder-access">
    <q-checkbox v-model="allFolders" :disable="disable" :label="t('connection.mail.allFolders')" />
    <div class="text-caption text-grey-7 q-mb-sm">{{ t('connection.mail.foldersHint') }}</div>
    <q-btn v-if="connectionId !== null && !disable" outline color="primary" icon="refresh"
      :label="t('connection.mail.loadFolders')" :loading="loading" @click="loadFolders" />
    <div v-if="connectionId === null" class="text-caption q-mt-sm">{{ t('connection.mail.saveBeforeFolders') }}</div>
    <q-banner v-if="error" dense class="q-mt-sm" role="alert">{{ t('connection.mail.foldersError') }}</q-banner>
    <q-input v-if="options.length" v-model="filter" outlined dense clearable class="q-mt-sm"
      :label="t('connection.mail.filterFolders')" />
    <q-tree v-if="options.length" :nodes="treeNodes" node-key="key" v-model:expanded="expanded" no-selection
      :filter="filter ?? ''" :filter-method="folderMatches" class="mail-folder-list q-mt-sm">
      <template #default-header="{ node }">
        <q-checkbox :model-value="node.folderSelectable && (allFolders || selected.includes(node.name))"
          :disable="disable || !node.folderSelectable" :aria-label="node.fullLabel" @click.stop
          @update:model-value="checked => toggleFolder(node.name, checked === true)" />
        <div class="mail-folder-name">
          <div>{{ node.label }}</div>
          <div v-if="!node.folderSelectable" class="text-caption">{{ t('connection.mail.folderContainer') }}</div>
        </div>
      </template>
    </q-tree>
    <div v-else-if="loaded && !error" class="text-caption q-mt-sm">{{ t('connection.mail.noFolders') }}</div>
    <div v-if="invalid" class="text-negative q-mt-sm" role="alert">{{ t('connection.mail.selectFolder') }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useFormChild } from 'quasar'
import { mailService, type MailFolderOption } from '../services/mailService'

const props = defineProps<{ connectionId: number | null; disable?: boolean }>()
const model = defineModel<string>({ default: '' })
const { t } = useI18n()
const folders = ref<MailFolderOption[]>([])
const filter = ref<string | null>('')
const loading = ref(false)
const loaded = ref(false)
const error = ref(false)
const invalid = ref(false)
let request: AbortController | null = null
let writtenValue: string | undefined
const allEnabled = ref(true)
const selected = ref<string[]>([])

watch(model, value => {
  if (value === writtenValue) { writtenValue = undefined; return }
  const raw = value.trim()
  if (raw.startsWith('[')) {
    try {
      const values: unknown = JSON.parse(raw)
      if (Array.isArray(values) && values.every((value): value is string => typeof value === 'string')) {
        selected.value = values.map(name => name.toUpperCase() === 'INBOX' ? 'INBOX' : name)
        allEnabled.value = values.length === 0
        return
      }
    } catch { /* Preserve legacy names if this is not a JSON list. */ }
  }
  selected.value = raw.split(',').map(name => name.trim()).filter(Boolean).map(name => name.toUpperCase() === 'INBOX' ? 'INBOX' : name)
  allEnabled.value = selected.value.length === 0
}, { immediate: true })

function writeSelection(): void {
  writtenValue = JSON.stringify(allEnabled.value ? [] : selected.value)
  model.value = writtenValue
}
const allFolders = computed({
  get: () => allEnabled.value,
  set: (value: boolean) => {
    allEnabled.value = value
    selected.value = value ? [] : folders.value.filter(folder => folder.selectable).map(folder => folder.name)
    writeSelection()
    invalid.value = false
  },
})
const options = computed(() => {
  const present = new Set(folders.value.map(folder => folder.name))
  return [...folders.value, ...selected.value.filter(name => !present.has(name)).map(name => ({ name, label: name, delimiter: null, selectable: true }))]
})
interface FolderNode {
  key: string
  name: string
  label: string
  fullLabel: string
  folderSelectable: boolean
  children: FolderNode[]
}
const expanded = ref<string[]>([])
let knownBranches = new Set<string>()
const treeNodes = computed(() => {
  const roots: FolderNode[] = []
  const indexed = new Map<string, FolderNode>()
  for (const folder of options.value) {
    const parts = folder.delimiter ? folder.name.split(folder.delimiter) : [folder.name]
    let siblings = roots
    for (let index = 0; index < parts.length; index++) {
      const path = parts.slice(0, index + 1).join(folder.delimiter ?? '')
      const key = JSON.stringify([folder.delimiter, path])
      let node = indexed.get(key)
      if (!node) {
        node = { key, name: path, label: parts[index] || folder.delimiter || folder.label, fullLabel: path,
          folderSelectable: false, children: [] }
        indexed.set(key, node)
        siblings.push(node)
      }
      if (index === parts.length - 1) {
        node.folderSelectable = folder.selectable
        node.fullLabel = folder.label
      }
      siblings = node.children
    }
  }
  return roots
})
watch(treeNodes, roots => {
  const branches = new Set<string>()
  const visit = (nodes: FolderNode[]): void => {
    for (const node of nodes) if (node.children.length) { branches.add(node.key); visit(node.children) }
  }
  visit(roots)
  expanded.value = [...new Set([...expanded.value.filter(key => branches.has(key)), ...[...branches].filter(key => !knownBranches.has(key))])]
  knownBranches = branches
})
function folderMatches(node: FolderNode, value: string): boolean {
  return node.fullLabel.toLocaleLowerCase().includes(value.toLocaleLowerCase())
}

function toggleFolder(name: string, checked: boolean): void {
  const next = new Set(allFolders.value ? folders.value.filter(folder => folder.selectable).map(folder => folder.name) : selected.value)
  if (checked) next.add(name)
  else next.delete(name)
  allEnabled.value = false
  selected.value = [...next]
  writeSelection()
  invalid.value = false
}

async function loadFolders(): Promise<void> {
  request?.abort()
  if (props.connectionId === null || props.disable) return
  const pending = new AbortController()
  request = pending
  loading.value = true
  error.value = false
  try {
    const response = await mailService.listMailboxes(props.connectionId, pending.signal)
    if (request !== pending || pending.signal.aborted) return
    folders.value = response.data
    loaded.value = true
  } catch {
    if (request === pending && !pending.signal.aborted) error.value = true
  } finally {
    if (request === pending) loading.value = false
  }
}

watch(() => [props.connectionId, props.disable] as const, () => {
  request?.abort()
  folders.value = []
  filter.value = ''
  loaded.value = error.value = invalid.value = loading.value = false
  void loadFolders()
}, { immediate: true })
onBeforeUnmount(() => request?.abort())
useFormChild({
  validate: () => {
    invalid.value = !props.disable && !allFolders.value && (selected.value.length === 0 || selected.value.length > 500)
    return !invalid.value
  },
  resetValidation: () => { invalid.value = false },
  requiresQForm: false,
})
</script>

<style scoped>
.mail-folder-list { max-height: 320px; overflow: auto; }
.mail-folder-name { overflow-wrap: anywhere; }
</style>
