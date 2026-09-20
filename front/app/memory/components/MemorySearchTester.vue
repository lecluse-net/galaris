<template>
  <q-card flat bordered class="memory-search-tester q-my-md">
    <q-card-section class="memory-search-tester__form">
      <form
        class="memory-search-tester__search-row"
        @submit.prevent="runSearch"
      >
        <div class="memory-search-tester__agent">
          <slot name="agent" />
        </div>
        <q-input
          v-model="query"
          class="memory-search-tester__query"
          outlined
          dense
          clearable
          maxlength="4000"
          :disable="loading"
          :label="t('memory.searchTester.query')"
          :placeholder="t('memory.searchTester.queryPlaceholder')"
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
        <q-select
          v-model="selectedTypes"
          class="memory-search-tester__types"
          :options="typeOptions"
          behavior="menu"
          outlined
          dense
          multiple
          emit-value
          map-options
          :use-chips="$q.screen.lt.md"
          :disable="loading"
          :label="t('memory.type')"
        />
        <q-btn
          class="memory-search-tester__search-button"
          color="primary"
          icon="manage_search"
          type="submit"
          no-wrap
          unelevated
          :label="t('memory.searchTester.run')"
          :disable="!query.trim()"
          :loading="loading"
        />
      </form>
    </q-card-section>

    <q-linear-progress v-if="loading" indeterminate color="primary" />

    <template v-if="agentId !== null && error">
      <q-separator />
      <q-banner class="bg-red-1 text-negative">
        <template #avatar><q-icon name="error_outline" /></template>
        {{ t('memory.searchTester.error') }}
        <template #action>
          <q-btn
            flat
            color="negative"
            :label="t('memory.retry')"
            :disable="!query.trim()"
            @click="runSearch"
          />
        </template>
      </q-banner>
    </template>

    <template v-if="agentId !== null && result">
      <q-separator />
      <q-card-section>
        <div class="row items-center q-gutter-sm">
          <q-chip dense outline icon="timer">
            {{ t('memory.searchTester.elapsed', { milliseconds: elapsedMs }) }}
          </q-chip>
          <q-chip dense outline icon="format_list_numbered">
            {{ t('memory.searchTester.resultCount', { count: result.length }) }}
          </q-chip>
        </div>
      </q-card-section>

      <q-list v-if="result.length" bordered separator>
        <q-item
          v-for="(item, index) in result"
          :key="item.id"
          :clickable="item.node_kind !== 'folder'"
          @click="item.node_kind !== 'folder' && emit('open', item.id)"
        >
          <q-item-section avatar>
            <q-avatar color="primary" text-color="white" size="32px">
              {{ index + 1 }}
            </q-avatar>
          </q-item-section>
          <q-item-section>
            <q-item-label class="text-weight-medium">
              {{ item.title }}
            </q-item-label>
            <q-item-label caption>
              {{ t(`memory.types.${item.memory_type}`) }}
            </q-item-label>
            <q-item-label class="memory-search-tester__excerpt q-mt-xs">
              {{ item.excerpt }}
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>

      <q-banner v-else class="bg-grey-2">
        <template #avatar><q-icon name="search_off" /></template>
        {{ t('memory.searchTester.empty') }}
      </q-banner>
    </template>
  </q-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { websocket } from '@/core/websocket'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { memoryService } from '../services/memoryService'
import { excludeMemorySearchResults } from './searchResults'
import type {
  MemoryRankedItem,
  MemoryType,
} from '../types'

const { agentId } = defineProps<{
  agentId: number | null
}>()

const emit = defineEmits<{
  open: [id: string]
}>()

const { t } = useI18n()
const $q = useQuasar()
const query = ref('')
const selectedTypes = ref<MemoryType[]>([])
const loading = ref(false)
const error = ref(false)
const result = ref<MemoryRankedItem[] | null>(null)
const elapsedMs = ref(0)
const excludedItemIds = new Set<string>()
let requestVersion = 0

const memoryTypes: MemoryType[] = [
  'core',
  'working',
  'episodic',
  'semantic',
  'procedural',
  'social',
]
const typeOptions = computed(() => memoryTypes.map(value => ({
  value,
  label: t(`memory.types.${value}`),
})))
async function runSearch(): Promise<void> {
  const normalizedQuery = query.value.trim()
  if (agentId === null || !normalizedQuery) return

  const currentRequest = ++requestVersion
  const startedAt = performance.now()
  loading.value = true
  error.value = false
  try {
    const response = await memoryService.search({
      agentId,
      query: normalizedQuery,
      memoryTypes: selectedTypes.value,
    })
    if (currentRequest !== requestVersion) return
    result.value = excludeMemorySearchResults(response, excludedItemIds)
    elapsedMs.value = Math.max(0, Math.round(performance.now() - startedAt))
  } catch {
    if (currentRequest !== requestVersion) return
    error.value = true
    result.value = null
  } finally {
    if (currentRequest === requestVersion) loading.value = false
  }
}

function removeResult(itemId: string): void {
  excludedItemIds.add(itemId)
  if (result.value !== null) {
    result.value = excludeMemorySearchResults(result.value, excludedItemIds)
  }
}

function invalidateAccess(): void {
  requestVersion += 1
  excludedItemIds.clear()
  loading.value = false
  error.value = false
  result.value = null
  elapsedMs.value = 0
}
watch(() => agentId, invalidateAccess)
websocket.onEvent('memory', 'invalidate', invalidateAccess)
websocket.onConnect(invalidateAccess)
onBeforeUnmount(() => {
  requestVersion++
  websocket.offEvent('memory', 'invalidate', invalidateAccess)
  websocket.offConnect(invalidateAccess)
})

defineExpose({ removeResult })
</script>

<style scoped>
.memory-search-tester__form {
  padding: 10px 12px;
}

.memory-search-tester__search-row {
  display: grid;
  grid-template-areas: 'agent query types button';
  grid-template-columns: minmax(180px, 0.8fr) minmax(240px, 1.4fr) minmax(190px, 0.8fr) auto;
  gap: 8px;
  align-items: stretch;
}

.memory-search-tester__agent {
  grid-area: agent;
  min-width: 0;
}

.memory-search-tester__query {
  grid-area: query;
  min-width: 0;
}

.memory-search-tester__search-button {
  grid-area: button;
  min-width: 190px;
}

.memory-search-tester__types {
  grid-area: types;
  min-width: 0;
}

.memory-search-tester__excerpt {
  white-space: pre-line;
  overflow-wrap: anywhere;
}

@media (min-width: 1024px) {
  .memory-search-tester__search-row :deep(.q-field__control),
  .memory-search-tester__search-row :deep(.q-field__marginal),
  .memory-search-tester__search-button {
    height: 40px;
    min-height: 40px;
  }
}

@media (max-width: 1023.98px) {
  .memory-search-tester__search-row {
    grid-template-areas:
      'agent types'
      'query button';
    grid-template-columns: minmax(0, 1fr) minmax(220px, 0.65fr);
  }
}

@media (max-width: 599.98px) {
  .memory-search-tester__form {
    padding: 8px;
  }

  .memory-search-tester__search-row {
    grid-template-areas:
      'agent'
      'query'
      'types'
      'button';
    grid-template-columns: 1fr;
  }

  .memory-search-tester__search-button {
    width: 100%;
    min-height: 44px;
  }
}
</style>
