<template>
  <q-page class="q-pa-md">
    <PageHeader help-key="memory" :help-text="$t('contextHelpPages.memory')" :icon="navigationIcon('memory')" :title="t('nav.memory')" />

    <q-tabs
      v-model="activeTab"
      class="text-primary"
      active-color="primary"
      indicator-color="primary"
      align="left"
    >
      <q-tab name="list" icon="view_list" :label="t('memory.tabs.list')" />
      <q-tab name="graph" icon="hub" :label="t('memory.tabs.graph')" />
    </q-tabs>
    <q-separator />

    <q-card flat bordered class="memory-filter-block q-my-md">
      <q-form class="memory-filter-block__form" @submit="temporalFilter?.apply()">
        <div class="memory-filter-block__row memory-filter-block__row--primary">
          <div class="memory-filter-block__field">
            <AgentSelect
              v-model="store.selectedAgentId"
              class="memory-agent-select"
              :options="agentOptions"
              behavior="menu"
              emit-value
              map-options
              outlined
              dense
              options-dense
              :label="t('memory.agent')"
              :loading="agentStore.loading"
            />
          </div>
          <div class="memory-filter-block__field">
            <q-input
              v-model="store.query"
              outlined
              dense
              clearable
              debounce="350"
              :placeholder="t('memory.search')"
              @update:model-value="scheduleSearch"
            >
              <template #prepend><q-icon name="search" /></template>
            </q-input>
          </div>
        </div>

        <div
          class="memory-filter-block__row memory-filter-block__row--secondary"
          :class="{ 'memory-filter-block__row--list': activeTab === 'list' }"
        >
          <div class="memory-filter-block__field">
            <q-select
              v-model="store.selectedTopicItemId"
              :options="topicFilterOptions"
              behavior="menu"
              outlined
              dense
              clearable
              emit-value
              map-options
              options-dense
              :loading="filterOptionsLoading"
              :label="t('memory.topicFilter')"
              @update:model-value="() => searchSafely(true)"
            />
          </div>
          <div class="memory-filter-block__field">
            <q-select
              v-model="store.selectedContactItemId"
              :options="contactFilterOptions"
              behavior="menu"
              outlined
              dense
              clearable
              emit-value
              map-options
              options-dense
              :loading="filterOptionsLoading"
              :label="t('memory.contactFilter')"
              @update:model-value="() => searchSafely(true)"
            />
          </div>
          <div v-if="activeTab === 'list'" class="memory-filter-block__temporal">
            <MemoryTemporalFilter ref="temporalFilter" v-model="store.temporal" :timezone="store.temporalTimezone" @update:model-value="() => searchSafely(true)" />
            <q-btn type="submit" color="primary" outline icon="refresh" :label="t('memory.temporalSearch.apply')" />
          </div>
        </div>
      </q-form>
    </q-card>

    <q-tab-panels v-model="activeTab" animated class="bg-transparent">
      <q-tab-panel name="list" class="q-pa-none">
        <section>
        <div class="row justify-end items-center q-gutter-md q-mb-md">
          <div class="row q-gutter-sm">
            <q-btn
              v-if="canEdit"
              color="primary"
              icon="add"
              :label="t('memory.new')"
              :disable="store.selectedAgentId === null"
              @click="openCreate"
            />
          </div>
        </div>

        <q-banner v-if="store.error" rounded class="bg-red-1 text-negative q-mb-md">
          {{ t('memory.loadError') }}
          <template #action>
            <q-btn flat color="negative" :label="t('memory.retry')" @click="searchSafely()" />
          </template>
        </q-banner>

        <div v-if="store.recallTruncated" class="text-caption q-mb-md" role="status">
          {{ t('memory.recall.bounded') }}
        </div>
        <div v-if="store.degradationReason" class="text-caption q-mb-md" role="status">
          {{ t('memory.recall.degraded') }}
        </div>

        <q-table
          flat
          bordered
          :row-key="row => row.item.id"
          :rows="store.hits"
          :columns="itemColumns"
          :loading="store.loading"
          :grid="$q.screen.lt.md"
          class="memory-list-table"
          :pagination="{
            page: store.page,
            rowsPerPage: store.rowsPerPage,
            rowsNumber: store.total,
            sortBy: store.sortBy,
            descending: store.sortDescending,
          }"
          :rows-per-page-options="store.rowsPerPageOptions"
          :no-data-label="store.selectedAgentId === null ? t('memory.selectAgent') : t('memory.empty')"
          @row-click="(_, hit) => hit.item.node_kind !== 'folder' && openDetail(hit.item.id)"
          @request="onTableRequest"
        >
          <template #body-cell-title="props">
            <q-td :props="props">
              <div class="row items-start no-wrap q-gutter-sm">
                <MemoryItemThumbnail :key="props.row.item.id + ':' + props.row.item.node_kind" :item="props.row.item" :agent-id="store.selectedAgentId" />
                <div class="col memory-list-copy">
                  <div class="row items-center q-gutter-xs">
                    <DocumentIcon v-if="props.row.item.node_kind === 'document'" :document-id="props.row.item.id" :title="props.row.item.title" />
                    <span class="text-weight-medium">{{ props.row.item.title }}</span>
                    <q-chip
                      v-if="props.row.item.node_kind === 'document'"
                      dense
                      color="orange-1"
                      text-color="orange-10"
                      icon="description"
                    >
                      {{ t('memory.kinds.document') }}
                    </q-chip>
                    <q-chip v-if="props.row.item.source_managed" dense color="blue-1" text-color="primary" icon="sync_lock">
                      {{ t('memory.generated') }}
                    </q-chip>
                    <q-chip v-else-if="props.row.item.deletion_protected" dense color="purple-1" text-color="purple-10" icon="lock">
                      {{ t('memory.protected') }}
                    </q-chip>
                    <q-chip v-if="props.row.item.old_at" dense color="grey-4" text-color="grey-9" icon="history">
                      {{ t('memory.findings.old') }}
                    </q-chip>
                    <q-chip
                      v-for="finding in store.findingsFor(props.row.item.id)"
                      :key="finding.id"
                      clickable
                      dense
                      :color="findingColor(finding.kind)"
                      text-color="white"
                      :icon="findingIcon(finding.kind)"
                      @click.stop="openFinding(finding)"
                    >
                      {{ findingLabel(finding) }}
                    </q-chip>
                  </div>
                  <div class="memory-excerpt text-caption text-grey-7 ellipsis-2-lines">
                    {{ props.row.excerpt }}
                  </div>
                  <div v-if="props.row.temporal_match_at" class="text-caption">
                    {{ t('memory.temporalSearch.match', { date: formatTemporalDate(props.row.temporal_match_at) }) }}
                  </div>
                </div>
              </div>
            </q-td>
          </template>
          <template #body-cell-visibility="props">
            <q-td :props="props">
              <q-icon :name="visibilityIcon(props.row.item.visibility)" class="q-mr-xs" />
              {{ t(`memory.visibilities.${props.row.item.visibility}`) }}
            </q-td>
          </template>
          <template #body-cell-owner="props">
            <q-td :props="props">{{ agentLabel(props.row.item.owner_agent_id) }}</q-td>
          </template>
          <template #body-cell-access_count="props">
            <q-td :props="props">
              {{ formatNumber(props.row.item.access_count) }}
            </q-td>
          </template>
          <template #body-cell-last_accessed_at="props">
            <q-td :props="props">
              {{ formatDate(props.row.item.last_accessed_at) }}
            </q-td>
          </template>
          <template #body-cell-updated_at="props">
            <q-td :props="props">{{ formatDate(props.row.item.updated_at || props.row.item.created_at) }}</q-td>
          </template>
          <template #body-cell-actions="props">
            <q-td :props="props" class="q-gutter-xs">
              <MemoryAttachmentButton v-if="props.row.item.node_kind === 'attachment'"
                :item-id="props.row.item.id" :agent-id="store.selectedAgentId" icon-only />
            </q-td>
          </template>
          <template #item="props">
            <div class="q-table__grid-item col-12 memory-list-grid-item">
              <q-card
                flat
                bordered
                class="memory-mobile-card"
                :class="{ 'cursor-pointer': props.row.item.node_kind !== 'folder' }"
                :role="props.row.item.node_kind !== 'folder' ? 'button' : undefined"
                :tabindex="props.row.item.node_kind !== 'folder' ? 0 : undefined"
                @click="props.row.item.node_kind !== 'folder' && openDetail(props.row.item.id)"
                @keyup.enter.self="props.row.item.node_kind !== 'folder' && openDetail(props.row.item.id)"
              >
                <q-card-section class="q-gutter-md">
                  <div v-if="props.row.temporal_match_at" class="text-caption">
                    {{ t('memory.temporalSearch.match', { date: formatTemporalDate(props.row.temporal_match_at) }) }}
                  </div>
                  <div class="row items-start no-wrap q-gutter-sm">
                    <MemoryItemThumbnail :key="props.row.item.id + ':' + props.row.item.node_kind" :item="props.row.item" :agent-id="store.selectedAgentId" />
                    <div class="col memory-mobile-copy">
                      <div class="text-subtitle1 text-weight-medium memory-mobile-title">
                        <DocumentIcon v-if="props.row.item.node_kind === 'document'" :document-id="props.row.item.id" :title="props.row.item.title" class="q-mr-sm" />
                        {{ props.row.item.title }}
                      </div>
                    </div>
                    <MemoryAttachmentButton v-if="props.row.item.node_kind === 'attachment'"
                      :item-id="props.row.item.id" :agent-id="store.selectedAgentId" icon-only />
                  </div>

                  <div class="row items-center q-gutter-xs memory-mobile-badges">
                    <q-chip
                      v-if="props.row.item.node_kind === 'document'"
                      dense
                      color="orange-1"
                      text-color="orange-10"
                      icon="description"
                    >
                      {{ t('memory.kinds.document') }}
                    </q-chip>
                    <q-chip
                      v-if="props.row.item.source_managed"
                      dense
                      color="blue-1"
                      text-color="primary"
                      icon="sync_lock"
                    >
                      {{ t('memory.generated') }}
                    </q-chip>
                    <q-chip
                      v-else-if="props.row.item.deletion_protected"
                      dense
                      color="purple-1"
                      text-color="purple-10"
                      icon="lock"
                    >
                      {{ t('memory.protected') }}
                    </q-chip>
                    <q-chip
                      v-if="props.row.item.old_at"
                      dense
                      color="grey-4"
                      text-color="grey-9"
                      icon="history"
                    >
                      {{ t('memory.findings.old') }}
                    </q-chip>
                    <q-chip
                      v-for="finding in store.findingsFor(props.row.item.id)"
                      :key="finding.id"
                      clickable
                      dense
                      :color="findingColor(finding.kind)"
                      text-color="white"
                      :icon="findingIcon(finding.kind)"
                      @click.stop="openFinding(finding)"
                    >
                      {{ findingLabel(finding) }}
                    </q-chip>
                  </div>

                  <div class="text-body2 text-grey-7 memory-mobile-excerpt">
                    {{ props.row.excerpt || '—' }}
                  </div>

                  <div class="memory-mobile-fields">
                    <div class="memory-mobile-field">
                      <div class="memory-mobile-label">{{ t('memory.visibility') }}</div>
                      <div class="q-mt-xs">
                        <q-icon :name="visibilityIcon(props.row.item.visibility)" class="q-mr-xs" />
                        {{ t(`memory.visibilities.${props.row.item.visibility}`) }}
                      </div>
                    </div>
                    <div class="memory-mobile-field memory-mobile-field--wide">
                      <div class="memory-mobile-label">{{ t('memory.owner') }}</div>
                      <div class="q-mt-xs memory-mobile-value">
                        {{ agentLabel(props.row.item.owner_agent_id) }}
                      </div>
                    </div>
                    <div class="memory-mobile-field">
                      <div class="memory-mobile-label">{{ t('memory.accessCount') }}</div>
                      <div class="q-mt-xs">{{ formatNumber(props.row.item.access_count) }}</div>
                    </div>
                    <div class="memory-mobile-field">
                      <div class="memory-mobile-label">{{ t('memory.lastAccessed') }}</div>
                      <div class="q-mt-xs memory-mobile-value">
                        {{ formatDate(props.row.item.last_accessed_at) }}
                      </div>
                    </div>
                    <div class="memory-mobile-field memory-mobile-field--wide">
                      <div class="memory-mobile-label">{{ t('memory.updated') }}</div>
                      <div class="q-mt-xs memory-mobile-value">
                        {{ formatDate(props.row.item.updated_at || props.row.item.created_at) }}
                      </div>
                    </div>
                  </div>
                </q-card-section>
              </q-card>
            </div>
          </template>
          </q-table>
        </section>
      </q-tab-panel>

      <q-tab-panel name="graph" class="q-pa-none">
        <MemoryGraph
          ref="memoryGraph"
          v-if="activeTab === 'graph'"
          :agent-id="store.selectedAgentId"
          :query="store.query"
          :topic-item-id="store.selectedTopicItemId"
          :contact-item-id="store.selectedContactItemId"
          @open="openDetail"
        />
      </q-tab-panel>
    </q-tab-panels>

    <MemoryItemDialog v-if="selectedItemId && store.selectedAgentId !== null" :key="selectedItemId"
      :item-id="selectedItemId" :agent-id="store.selectedAgentId" :state="store" :graph-context="graphContext"
      @close="selectedItemId = null; graphContext = null; memoryGraph?.closeDetails()" @graph-neighbor="openGraphNeighbor" />

    <q-dialog allow-focus-outside v-model="editorDialog" :maximized="$q.screen.lt.md">
      <q-card class="memory-editor galaris-dialog-card">
        <q-toolbar class="galaris-dialog-title">
          <q-toolbar-title>{{ editingId ? t('memory.editTitle') : t('memory.createTitle') }}</q-toolbar-title>
          <q-btn flat round dense icon="close" :aria-label="t('memory.close')" v-close-popup />
        </q-toolbar>
        <div class="galaris-dialog-body">
          <MemoryItemForm :draft="editor" :editing-id="editingId" :lock-version="store.currentItem?.lock_version"
            :readonly="editorSaving"
            :keyword-options="memoryKeywordOptions"
            :sharing-editable="canEdit || canAdminister" @update:draft="Object.assign(editor, $event)" @sharing-changed="onSharingChanged" />
        </div>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn
            v-if="canEdit"
            color="primary"
            icon="save"
            :label="t('memory.save')"
            :disable="store.selectedAgentId === null"
            :loading="editorSaving"
            @click="saveEditor"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <MemoryFindingDialog
      v-if="selectedFinding && store.selectedAgentId !== null"
      :finding="selectedFinding"
      :agent-id="store.selectedAgentId"
      :saving="store.saving"
      @close="selectedFinding = null"
      @resolved="resolveFinding"
    />
  </q-page>
</template>

<script setup lang="ts">
import { DocumentIcon } from '@/app/document'
import MemoryItemThumbnail from '../components/MemoryItemThumbnail.vue'
import MemoryAttachmentButton from '../components/MemoryAttachmentButton.vue'
import { navigationIcon } from '@/core/navigation'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useQuasar, type QTableProps } from 'quasar'
import { apiErrorDetail, isCancelledRequest } from '@/core/api'
import { PageHeader } from '@/core/util'
import { privileges } from '@/core/authorize'
import { usePrivilegeStore } from '@/core/authorize/stores/privilegeStore'
import { useAgentChoices } from '@/app/agent'
import { AgentSelect, useAgentSelectionStore } from '@/app/agent'
import MemoryGraph from '../components/MemoryGraph.vue'
import MemoryFindingDialog from '../components/MemoryFindingDialog.vue'
import MemoryTemporalFilter from '../components/MemoryTemporalFilter.vue'
import MemoryItemForm from '../components/MemoryItemForm.vue'
import MemoryItemDialog from '../components/MemoryItemDialog.vue'
import { useMemoryStore } from '../stores/memoryStore'
import { memoryService } from '../services/memoryService'
import type {
  MemoryItem,
  MemoryGraphNode,
  MemoryGraphRelation,
  MemoryFinding,
  MemoryFindingKind,
  MemoryNodeKind,
  MemorySortField,
  MemoryVisibility,
} from '../types'

const { t, locale } = useI18n()
function formatTemporalDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'medium', timeStyle: 'short', timeZone: store.temporalTimezone ?? 'UTC',
  }).format(new Date(value))
}
const route = useRoute()
const $q = useQuasar()
const store = useMemoryStore()
const agentStore = useAgentChoices()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_EDIT))
const canAdminister = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_ADMIN))
const activeTab = ref<'list' | 'graph'>('list')
const selectedItemId = ref<string | null>(null)
const memoryGraph = useTemplateRef<InstanceType<typeof MemoryGraph>>('memoryGraph')
const graphContext = ref<{ node: MemoryGraphNode; relations: MemoryGraphRelation[] } | null>(null)
const editorDialog = ref(false)
const editorSaving = ref(false)
const memoryKeywordOptions = computed(() => [...new Set(store.hits.flatMap(hit => hit.item.keywords))])
const editingId = ref<string | null>(null)
const selectedFinding = ref<MemoryFinding | null>(null)
const temporalFilter = useTemplateRef<InstanceType<typeof MemoryTemporalFilter>>('temporalFilter')
const filterOptionsLoading = ref(false)
const topicFilterOptions = ref<{ value: string, label: string }[]>([])
const contactFilterOptions = ref<{ value: string, label: string }[]>([])
type TableRequest = Parameters<NonNullable<QTableProps['onRequest']>>[0]
const agentOptions = computed(() => agentStore.agents.map(agent => ({
  value: agent.id,
  label: agent.label,
})))
const itemColumns = computed<QTableProps['columns']>(() => [
  {
    name: 'title',
    label: t('memory.title'),
    field: (row: { item: MemoryItem }) => row.item.title,
    align: 'left',
    sortable: true,
  },
  {
    name: 'visibility',
    label: t('memory.visibility'),
    field: (row: { item: MemoryItem }) => row.item.visibility,
    align: 'left',
    sortable: true,
  },
  {
    name: 'owner',
    label: t('memory.owner'),
    field: (row: { item: MemoryItem }) => agentLabel(row.item.owner_agent_id),
    align: 'left',
    sortable: true,
  },
  {
    name: 'access_count',
    label: t('memory.accessCount'),
    field: (row: { item: MemoryItem }) => row.item.access_count,
    align: 'right',
    sortable: true,
    sortOrder: 'da',
  },
  {
    name: 'last_accessed_at',
    label: t('memory.lastAccessed'),
    field: (row: { item: MemoryItem }) => row.item.last_accessed_at,
    align: 'left',
    sortable: true,
    sortOrder: 'da',
  },
  {
    name: 'updated_at',
    label: t('memory.updated'),
    field: (row: { item: MemoryItem }) => row.item.updated_at || row.item.created_at,
    align: 'left',
    sortable: true,
    sortOrder: 'da',
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
])

const editor = reactive({
  temporal: null as import('../types').MemoryTemporalAnchor | null,
  content: '',
  nodeKind: 'memory' as MemoryNodeKind,
  keywords: [] as string[],
  revision: null as number | null,
  lockVersion: null as number | null,
  mediaType: 'text/html', contentType: 'text',
})
function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(locale.value).format(value)
}

function agentLabel(agentId: number | null): string {
  if (agentId === null) return t('memory.publicOwner')
  return agentOptions.value.find(option => option.value === agentId)?.label ?? `#${agentId}`
}



function visibilityIcon(visibility: MemoryVisibility): string {
  return ({ private: 'lock', shared: 'group', public: 'public' })[visibility]
}

function findingIcon(kind: MemoryFindingKind): string {
  return ({ duplicate: 'content_copy', contradiction: 'compare_arrows', aging: 'history' })[kind]
}

function findingColor(kind: MemoryFindingKind): string {
  return ({ duplicate: 'orange-8', contradiction: 'red-7', aging: 'blue-grey-7' })[kind]
}

function findingLabel(finding: MemoryFinding): string {
  const label = t(`memory.findings.kinds.${finding.kind}`)
  if (finding.score === null) return label
  const score = new Intl.NumberFormat(locale.value, {
    style: 'percent',
    maximumFractionDigits: 1,
  }).format(finding.score)
  return `${label} · ${score}`
}

function openFinding(finding: MemoryFinding): void {
  selectedFinding.value = finding
}

async function resolveFinding(
  action: 'apply' | 'dismiss',
  canonicalItemId?: string,
): Promise<void> {
  if (selectedFinding.value === null) return
  try {
    await store.resolveFinding(selectedFinding.value, action, canonicalItemId)
    selectedFinding.value = null
    $q.notify({ type: 'positive', message: t(`memory.findings.${action}Done`) })
  } catch (error) {
    notifyError(error)
  }
}

function notifyError(error?: unknown): void {
  const detail = apiErrorDetail(error)
  $q.notify({
    type: 'negative',
    message: detail
      ? t('memory.operationErrorWithDetail', { detail })
      : t('memory.operationError'),
    multiLine: true,
    timeout: detail ? 10_000 : 5_000,
  })
}

async function searchSafely(resetPage = false): Promise<void> {
  try {
    await store.search({ resetPage })
  } catch (error) {
    notifyError(error)
  }
}

function scheduleSearch(): void {
  void searchSafely(true)
}

let filterOptionsVersion = 0
onBeforeUnmount(() => { filterOptionsVersion += 1 })
async function loadFilterOptions(agentId: number | null): Promise<void> {
  const version = ++filterOptionsVersion
  if (agentId === null) {
    filterOptionsLoading.value = false
    topicFilterOptions.value = []
    contactFilterOptions.value = []
    return
  }
  filterOptionsLoading.value = true
  try {
    const options = await memoryService.listFilterOptions(agentId)
    if (version !== filterOptionsVersion) return
    topicFilterOptions.value = options.topics.map(option => ({
      value: option.id,
      label: option.label,
    }))
    contactFilterOptions.value = options.contacts.map(option => ({
      value: option.id,
      label: option.label,
    }))
  } catch (error) {
    if (version === filterOptionsVersion && !isCancelledRequest(error)) notifyError(error)
  } finally {
    if (version === filterOptionsVersion) filterOptionsLoading.value = false
  }
}

function isMemorySortField(value: string | null): value is MemorySortField {
  return value === 'title'
    || value === 'visibility'
    || value === 'owner'
    || value === 'access_count'
    || value === 'last_accessed_at'
    || value === 'updated_at'
}

async function onTableRequest(request: TableRequest): Promise<void> {
  const requestedSortBy = request.pagination.sortBy
  const sortBy = isMemorySortField(requestedSortBy) ? requestedSortBy : null

  try {
    await store.search({
      page: request.pagination.page,
      rowsPerPage: request.pagination.rowsPerPage,
      sortBy,
      sortDescending: request.pagination.descending,
    })
  } catch (error) {
    notifyError(error)
  }
}

async function openDetail(id: string, node?: MemoryGraphNode, relations: MemoryGraphRelation[] = []): Promise<void> {
  if (store.hits.some(hit => hit.item.id === id && hit.item.node_kind === 'folder')) return
  graphContext.value = node ? { node, relations } : null
  selectedItemId.value = id
}
async function openGraphNeighbor(id: string): Promise<void> {
  selectedItemId.value = null
  graphContext.value = null
  memoryGraph.value?.closeDetails()
  await nextTick()
  memoryGraph.value?.selectNode(id)
}

function resetEditor(): void {
  Object.assign(editor, {
    temporal: null,
    content: '',
    nodeKind: 'memory',
    keywords: [], revision: null, lockVersion: null,
    mediaType: 'text/html', contentType: 'text',
  })
}

function openCreate(): void {
  editingId.value = null
  resetEditor()
  editorDialog.value = true
}


async function saveEditor(): Promise<void> {
  if (editorSaving.value || store.selectedAgentId === null) return
  editorSaving.value = true
  try {
    const created = await store.createItem({
      owner_agent_id: store.selectedAgentId,
      temporal: editor.temporal,
      payload: { text: editor.content },
      media_type: editor.mediaType,
      node_kind: editor.nodeKind,
      keywords: [...new Set(editor.keywords.map(value => value.trim()).filter(Boolean))],
    })
    editorDialog.value = false
    await openDetail(created.id)
    $q.notify({ type: 'positive', message: t('memory.createdDone') })
  } catch (error) { notifyError(error) }
  finally { editorSaving.value = false }
}


async function onSharingChanged(): Promise<void> {
  const id = editingId.value && editorDialog.value ? editingId.value : store.currentItem?.id
  if (!id) return
  try {
    await store.openItem(id)
    await store.search()
  } catch (error) {
    notifyError(error)
  }
}

let initializingAgent = true
const agentSelectionStore = useAgentSelectionStore()
let pageDisposed = false
onBeforeUnmount(() => { pageDisposed = true })
watch(() => store.selectedAgentId, (agentId, previousAgentId) => {
  if (agentId !== previousAgentId) {
    selectedItemId.value = null
    graphContext.value = null
    store.selectedTopicItemId = null
    store.selectedContactItemId = null
    topicFilterOptions.value = []
    contactFilterOptions.value = []
  }
  if (initializingAgent) return
  void Promise.all([
    loadFilterOptions(agentId),
    searchSafely(true),
  ]).catch(notifyError)
})

onMounted(async () => {
  try {
    await agentStore.fetchAgents()
    if (pageDisposed) return
    const rawAgentId = Array.isArray(route.query.agent) ? route.query.agent[0] : route.query.agent
    const requestedAgentId = rawAgentId ? Number(rawAgentId) : null
    const routeAgentId = requestedAgentId !== null
      && Number.isInteger(requestedAgentId)
      && agentStore.agents.some(agent => agent.id === requestedAgentId)
      ? requestedAgentId
      : null
    const nextAgentId = routeAgentId
      ?? (agentStore.agents.some(agent => agent.id === agentSelectionStore.selectedAgentId)
        ? agentSelectionStore.selectedAgentId : null)
      ?? (agentStore.agents.some(agent => agent.id === store.selectedAgentId) ? store.selectedAgentId : null)
      ?? agentSelectionStore.defaultAgentId(agentStore.agents)
      ?? null
    if (store.selectedAgentId !== nextAgentId) {
      store.selectedAgentId = nextAgentId
      await nextTick()
    }
    const rawContactId = Array.isArray(route.query.contact)
      ? route.query.contact[0]
      : route.query.contact
    if (typeof rawContactId === 'string' && rawContactId) {
      activeTab.value = 'list'
      store.selectedContactItemId = rawContactId
    }
    initializingAgent = false
    await Promise.all([
      loadFilterOptions(store.selectedAgentId),
      searchSafely(true),
    ])
  } catch (error) {
    notifyError(error)
  } finally {
    initializingAgent = false
  }
})

watch(() => [route.query.item_id, agentStore.agents.length] as const, async ([value]) => {
  if (typeof value !== 'string' || !/^[0-9a-f-]{36}$/.test(value)) return
  for (const agent of agentStore.agents) {
    try { await memoryService.getItem(value, agent.id); store.selectedAgentId = agent.id; await openDetail(value); return } catch { /* Try another managed agent without exposing inaccessible metadata. */ }
  }
  if (agentStore.agents.length) $q.notify({ type: 'negative', message: t('richEditor.unavailable') })
}, { immediate: true })
</script>

<style scoped>
.memory-filter-block__form {
  display: grid;
  gap: 12px;
  padding: 16px;
}

.memory-filter-block__row {
  display: grid;
  gap: 12px;
  align-items: start;
}

.memory-filter-block__row--primary {
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
}

.memory-filter-block :deep(.q-field__control),
.memory-filter-block :deep(.q-field__marginal) {
  min-height: 44px;
}

.memory-filter-block__temporal {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.memory-filter-block__temporal > .q-field {
  flex: 1;
  min-width: 0;
}

.memory-filter-block__temporal > .q-btn {
  min-height: 44px;
  flex: 0 0 auto;
}

.memory-agent-select :deep(.q-field__native > .row) {
  min-width: 0;
  max-width: 100%;
}

.memory-filter-block__row--secondary {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.memory-filter-block__row--list {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(300px, 1.4fr);
}

.memory-filter-block__field {
  min-width: 0;
}

.memory-list-table {
  min-width: 0;
  max-width: 100%;
}

.memory-list-table :deep(.q-table) {
  table-layout: fixed;
  width: 100%;
}

.memory-list-table :deep(th),
.memory-list-table :deep(td) {
  padding: 8px;
  white-space: normal;
  overflow-wrap: anywhere;
}

.memory-list-table :deep(th:first-child) {
  width: 30%;
}

.memory-list-table :deep(th:last-child) {
  width: 64px;
}

.memory-list-table :deep(.q-chip) {
  max-width: 100%;
  height: auto;
  min-height: 24px;
  white-space: normal;
}

.memory-list-table :deep(.q-chip__content) {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}

.memory-list-table :deep(.q-table__bottom),
.memory-list-table :deep(.q-table__control) {
  flex-wrap: wrap;
  gap: 8px;
}

.memory-list-table :deep(.q-table__bottom) {
  padding: 8px;
}

.memory-excerpt {
  max-width: 100%;
  overflow-wrap: anywhere;
}
.memory-mobile-card,
.memory-list-copy,
.memory-mobile-copy,
.memory-mobile-field {
  min-width: 0;
}

:deep(.memory-list-table .q-table__grid-content) {
  width: 100%;
  margin: 0;
}

:deep(.memory-list-table .q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
}

.memory-list-grid-item {
  padding: 8px 0;
}

.memory-mobile-title,
.memory-mobile-excerpt,
.memory-mobile-value {
  overflow-wrap: anywhere;
}

.memory-mobile-badges {
  row-gap: 4px;
}

.memory-mobile-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
}

.memory-mobile-field--wide {
  grid-column: 1 / -1;
}

.memory-mobile-label {
  color: #757575;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.memory-editor { width: 980px; max-width: 96vw; max-height: 92vh; overflow: auto; }
.memory-editor :deep(.q-toolbar__title) { font-size: 1rem; }
.member-editor { width: min(620px, 94vw); }

@media (max-width: 1023px) {
  .memory-filter-block__row--primary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .memory-filter-block__row--secondary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .memory-filter-block__temporal {
    grid-column: 1 / -1;
  }
}

@media (max-width: 599px) {
  .memory-filter-block__form {
    padding: 12px;
  }

  .memory-filter-block__row--primary,
  .memory-filter-block__row--secondary {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
