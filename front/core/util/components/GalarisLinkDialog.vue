<template>
  <q-dialog v-model="open" :maximized="$q.screen.lt.md" @hide="emit('hide')">
    <q-card class="galaris-link-dialog column no-wrap">
      <q-toolbar class="galaris-dialog-title">
        <q-icon name="add_link" size="sm" class="q-mr-sm" />
        <q-toolbar-title>{{ t('richEditor.galarisLink') }}</q-toolbar-title>
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('richEditor.close')" />
      </q-toolbar>

      <q-card-section class="q-pb-sm">
        <q-input v-model="query" autofocus outlined clearable :label="t('richEditor.searchContents')" :hint="t('richEditor.searchHint')">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
        <div class="row q-gutter-xs q-mt-sm" role="group" :aria-label="t('richEditor.contentType')">
          <q-btn v-for="kind in kinds" :key="kind" dense no-caps rounded :flat="filter !== kind" :unelevated="filter === kind"
            :color="filter === kind ? 'primary' : undefined" :label="t('richEditor.targetTypes.' + kind)"
            :aria-pressed="filter === kind" @click="filter = kind" />
        </div>
      </q-card-section>
      <q-separator />

      <div class="galaris-link-results col scroll" :aria-busy="searching">
        <div v-if="searching" class="galaris-link-state text-grey-7" role="status">
          <q-spinner color="primary" size="28px" />
          <span>{{ t('richEditor.searching') }}</span>
        </div>
        <div v-else-if="error" class="galaris-link-state" role="alert">
          <q-icon name="search_off" color="negative" size="32px" />
          <span>{{ t('richEditor.searchError') }}</span>
          <q-btn flat color="primary" :label="t('richEditor.retrySearch')" @click="scheduleSearch" />
        </div>
        <div v-else-if="!results.length" class="galaris-link-state text-grey-7" role="status">
          <q-icon name="search" size="32px" />
          <span>{{ t(normalizedQuery.length < 2 ? 'richEditor.searchHint' : 'richEditor.noResults') }}</span>
        </div>
        <q-list v-else separator :aria-label="t('richEditor.searchResults')">
          <q-item v-for="target in results" :key="target.uri" clickable :active="selected?.uri === target.uri"
            :aria-pressed="selected?.uri === target.uri" @click="select(target)">
            <q-item-section avatar><q-icon :name="icons[targetKind(target.uri)]" /></q-item-section>
            <q-item-section>
              <q-item-label class="galaris-link-result-title">{{ target.title }}</q-item-label>
              <q-item-label caption>{{ t('richEditor.targetTypes.' + targetKind(target.uri)) }}<span v-if="target.context"> · {{ target.context }}</span></q-item-label>
            </q-item-section>
            <q-item-section side><q-icon :name="selected?.uri === target.uri ? 'check_circle' : 'radio_button_unchecked'" :color="selected?.uri === target.uri ? 'primary' : 'grey-5'" /></q-item-section>
          </q-item>
        </q-list>
      </div>

      <q-separator />
      <q-card-section class="q-pb-sm">
        <div class="text-caption q-mb-sm galaris-link-selection" :title="selected?.title">
          {{ selected ? t('richEditor.selectedTarget', { title: selected.title }) : t('richEditor.selectTarget') }}
        </div>
        <q-input v-model="label" outlined dense :label="t('richEditor.linkText')" :disable="!selected" @update:model-value="labelEdited = true" @keydown.enter.prevent="insert" />
      </q-card-section>
      <q-card-actions align="right" class="q-px-md q-pb-md galaris-dialog-actions">
        <q-btn v-close-popup flat :label="t('richEditor.cancel')" />
        <q-btn unelevated color="primary" icon="add_link" :label="t('richEditor.insertLink')" :disable="!selected || !label.trim() || searching" @click="insert" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { searchRichLinks, type RichLinkTarget } from '../richText'

const open = defineModel<boolean>({ default: false })
const { initialLabel = '' } = defineProps<{ initialLabel?: string }>()
const emit = defineEmits<{ insert: [uri: string, label: string]; hide: [] }>()
const { t } = useI18n()
const kinds = ['all', 'document', 'memory', 'goal', 'task', 'agent'] as const
type TargetKind = Exclude<typeof kinds[number], 'all'>
const icons: Record<TargetKind, string> = { document: 'description', memory: 'psychology', goal: 'flag', task: 'task_alt', agent: 'smart_toy' }
const query = ref<string | null>(''), filter = ref<typeof kinds[number]>('all')
const targets = ref<RichLinkTarget[]>([]), selected = ref<RichLinkTarget>()
const label = ref(''), labelEdited = ref(false), searching = ref(false), error = ref(false)
const normalizedQuery = computed(() => query.value?.trim() ?? '')
const results = computed(() => targets.value.filter(target => filter.value === 'all' || targetKind(target.uri) === filter.value))
let generation = 0, timer: ReturnType<typeof setTimeout> | undefined

function targetKind(uri: string): TargetKind {
  if (uri.startsWith('document://')) return 'document'
  if (uri.startsWith('memory://')) return 'memory'
  return uri.split('/')[2] as TargetKind
}
function scheduleSearch(): void {
  const current = ++generation
  clearTimeout(timer)
  targets.value = []
  selected.value = undefined
  error.value = false
  searching.value = open.value && normalizedQuery.value.length >= 2
  if (!searching.value) return
  const search = normalizedQuery.value
  timer = setTimeout(async () => {
    try {
      const found = await searchRichLinks(search)
      if (current === generation) targets.value = found
    } catch {
      if (current === generation) error.value = true
    } finally {
      if (current === generation) searching.value = false
    }
  }, 300)
}
function select(target: RichLinkTarget): void {
  selected.value = target
  if (!labelEdited.value) label.value = initialLabel || target.title
}
function insert(): void {
  if (!selected.value || searching.value || !label.value.trim()) return
  emit('insert', selected.value.uri, label.value.trim())
  open.value = false
}
watch(normalizedQuery, scheduleSearch)
watch(filter, () => { if (selected.value && filter.value !== 'all' && targetKind(selected.value.uri) !== filter.value) selected.value = undefined })
watch(open, value => {
  ++generation
  clearTimeout(timer)
  searching.value = false
  if (value) {
    query.value = ''
    filter.value = 'all'
    targets.value = []
    selected.value = undefined
    label.value = initialLabel
    labelEdited.value = false
    error.value = false
  }
})
onBeforeUnmount(() => { ++generation; clearTimeout(timer) })
</script>

<style scoped>
.galaris-link-dialog { width: 760px; max-width: 94vw; height: 680px; max-height: 88vh; }
.galaris-link-results { min-height: 120px; }
.galaris-link-state { min-height: 180px; height: 100%; padding: 24px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; }
.galaris-link-result-title { overflow-wrap: anywhere; font-weight: 500; }
.galaris-link-selection { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.galaris-link-results .q-item { padding-block: 12px; }
.galaris-link-results .q-item--active { background: #1976d214; }
@media (max-width: 1023px) { .galaris-link-dialog { width: 100%; max-width: 100%; height: 100%; max-height: 100%; } }
</style>
