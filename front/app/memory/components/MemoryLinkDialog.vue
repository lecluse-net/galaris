<template>
  <q-dialog :model-value="true" :maximized="$q.screen.lt.md" @hide="emit('close')">
    <q-card class="memory-link-dialog column no-wrap">
      <q-toolbar class="galaris-dialog-title">
        <q-icon name="add_link" size="sm" class="q-mr-sm" />
        <q-toolbar-title>{{ t('memory.addLink') }}</q-toolbar-title>
        <q-btn
          v-close-popup
          flat
          round
          dense
          icon="close"
          :aria-label="t('memory.close')"
        />
      </q-toolbar>

      <q-card-section class="q-gutter-md col scroll">
        <div>
          <q-input
            v-model="searchQuery"
            autofocus
            clearable
            debounce="300"
            outlined
            :label="t('memory.linkTargetSearch')"
            :hint="t('memory.linkTargetSearchHint')"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>

          <q-linear-progress v-if="searching" indeterminate color="primary" class="q-mt-sm" />
          <q-banner v-else-if="searchError" rounded class="bg-red-1 text-negative q-mt-sm">
            {{ t('memory.linkTargetSearchError') }}
            <template #action>
              <q-btn flat color="negative" :label="t('memory.retry')" @click="searchTargets" />
            </template>
          </q-banner>
          <div
            v-else-if="normalizedQuery.length < MIN_SEARCH_LENGTH"
            class="text-caption text-grey-7 q-mt-sm"
          >
            {{ t('memory.linkTargetSearchMinimum', { count: MIN_SEARCH_LENGTH }) }}
          </div>
          <q-list
            v-else-if="searchResults.length"
            bordered
            separator
            class="memory-link-results q-mt-sm rounded-borders"
          >
            <q-item
              v-for="item in searchResults"
              :key="item.id"
              v-ripple
              clickable
              :active="selectedTarget?.id === item.id"
              active-class="bg-blue-1 text-primary"
              @click="selectedTarget = item"
            >
              <q-item-section side class="q-pr-sm">
                <DocumentIcon v-if="item.node_kind === 'document'" :document-id="item.id" :title="item.title" size="20px" />
                <q-icon v-else
                  name="psychology"
                  size="20px"
                />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ item.title }}</q-item-label>
                <q-item-label v-if="item.excerpt" caption lines="2">
                  {{ item.excerpt }}
                </q-item-label>
                <q-item-label caption>
                  {{ t(`memory.types.${item.memory_type}`) }} · {{ item.id }}
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-icon
                  :name="selectedTarget?.id === item.id ? 'check_circle' : 'radio_button_unchecked'"
                  :color="selectedTarget?.id === item.id ? 'primary' : 'grey-5'"
                />
              </q-item-section>
            </q-item>
          </q-list>
          <div v-else class="text-caption text-grey-7 q-mt-sm">
            {{ t('memory.linkTargetSearchEmpty') }}
          </div>
        </div>

        <q-banner v-if="selectedTarget" rounded class="bg-blue-1 text-primary">
          <div class="text-caption">{{ t('memory.linkTargetSelected') }}</div>
          <div class="text-weight-medium"><DocumentIcon v-if="selectedTarget.node_kind === 'document'" :document-id="selectedTarget.id" :title="selectedTarget.title" class="q-mr-sm" />{{ selectedTarget.title }}</div>
        </q-banner>

        <q-select
          v-model="relationType"
          :options="relationTypeOptions"
          behavior="menu"
          emit-value
          map-options
          outlined
          :label="t('memory.relationType')"
        />
      </q-card-section>

      <q-separator />
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn flat :label="t('memory.cancel')" v-close-popup />
        <q-btn
          color="primary"
          :label="t('memory.save')"
          :disable="selectedTarget === null"
          :loading="saving"
          @click="save"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import DocumentIcon from './DocumentIcon.vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { memoryService } from '../services/memoryService'
import type { MemoryRankedItem, MemoryRelationType } from '../types'

const props = defineProps<{
  sourceItemId: string
  agentId: number
  saving: boolean
}>()
const emit = defineEmits<{
  close: []
  save: [targetItemId: string, relationType: MemoryRelationType, targetTitle: string]
}>()
const { t } = useI18n()
const $q = useQuasar()

const MIN_SEARCH_LENGTH = 2
const relationTypes: readonly MemoryRelationType[] = [
  'related_to',
  'supports',
  'contradicts',
  'depends_on',
  'precedes',
  'supersedes',
]
const searchQuery = ref('')
const searchResults = ref<MemoryRankedItem[]>([])
const selectedTarget = ref<MemoryRankedItem | null>(null)
const relationType = ref<MemoryRelationType>('related_to')
const searching = ref(false)
const searchError = ref(false)
let requestVersion = 0

const normalizedQuery = computed(() => searchQuery.value.trim())
const relationTypeOptions = computed(() => relationTypes.map(value => ({
  value,
  label: t(`memory.relationTypes.${value}`),
})))

async function searchTargets(): Promise<void> {
  const query = normalizedQuery.value
  const version = ++requestVersion
  searchError.value = false
  if (query.length < MIN_SEARCH_LENGTH) {
    searchResults.value = []
    searching.value = false
    return
  }

  searching.value = true
  try {
    const result = await memoryService.search({
      agentId: props.agentId,
      query,
      limit: 20,
      excludeSourceManaged: true,
    })
    if (version !== requestVersion) return
    searchResults.value = result
      .filter(item => item.id !== props.sourceItemId)
      .slice(0, 20)
  } catch {
    if (version !== requestVersion) return
    searchResults.value = []
    searchError.value = true
  } finally {
    if (version === requestVersion) searching.value = false
  }
}

function save(): void {
  if (selectedTarget.value === null) return
  emit('save', selectedTarget.value.id, relationType.value, selectedTarget.value.title)
}

watch(searchQuery, () => {
  void searchTargets()
})

onBeforeUnmount(() => {
  requestVersion += 1
})
</script>

<style scoped>
.memory-link-dialog {
  width: min(720px, 94vw);
  max-height: min(820px, 92vh);
}

.memory-link-results {
  max-height: 360px;
  overflow-y: auto;
}
</style>
