<template>
  <q-card
    flat
    bordered
    class="memory-graph"
    :class="{
      'memory-graph--dark': $q.dark.isActive,
      'memory-graph--fullscreen': isFullscreen,
    }"
  >
    <q-card-section class="memory-graph__header row items-center justify-between q-gutter-md">
      <div>
        <div class="text-subtitle1 text-weight-medium">{{ t('memory.graph.title') }}</div>
      </div>
      <div class="memory-graph__header-actions row items-center q-gutter-sm">
        <q-chip dense outline icon="hub">
          {{ t('memory.graph.nodeCount', { count: visibleNodes.length }) }}
        </q-chip>
        <q-chip dense outline icon="timeline">
          {{ t('memory.graph.edgeCount', { count: visibleEdges.length }) }}
        </q-chip>
        <q-chip v-if="groupedNodeCount" dense outline icon="account_tree" role="status">
          {{ t('memory.graph.groupedCount', { count: groupedNodeCount }) }}
        </q-chip>
        <q-chip v-if="hiddenNodeCount" dense outline icon="visibility_off" role="status">
          {{ t('memory.graph.hiddenCount', { count: hiddenNodeCount }) }}
          <q-tooltip>{{ t('memory.graph.hiddenHint') }}</q-tooltip>
        </q-chip>
        <div class="memory-graph__refresh-controls row items-center no-wrap">
          <q-btn
            outline round dense color="primary" icon="restart_alt"
            :aria-label="t('memory.graph.resetPositions')"
            :disable="loading || reloading || layoutPending || threeUnavailable || !chartReady || !nodes.size"
            @click="resetPositions"
          >
            <q-tooltip>{{ t('memory.graph.resetPositions') }}</q-tooltip>
          </q-btn>
          <q-separator vertical inset class="q-mx-xs" />
          <q-toggle
            v-model="liveRefresh"
            dense
            color="positive"
            checked-icon="sync"
            unchecked-icon="sync_disabled"
            :label="t('memory.graph.liveRefresh')"
            :aria-label="t('memory.graph.liveRefresh')"
          >
            <q-tooltip>{{ t('memory.graph.liveRefreshHint') }}</q-tooltip>
          </q-toggle>
          <q-separator vertical inset class="q-mx-xs" />
          <q-btn
            flat
            round
            dense
            icon="refresh"
            :aria-label="t('memory.graph.reload')"
            :loading="loading || reloading || refreshing"
            :disable="loading || reloading || refreshing"
            @click="reload"
          >
            <q-tooltip>{{ t('memory.graph.reload') }}</q-tooltip>
          </q-btn>
        </div>
      </div>
    </q-card-section>

    <q-separator class="memory-graph__header-separator" />

    <q-banner
      v-if="agentId === null"
      class="memory-graph__banner memory-graph__banner--neutral bg-grey-2"
    >
      <template #avatar><q-icon name="person_search" /></template>
      {{ t('memory.selectAgent') }}
    </q-banner>

    <q-banner
      v-else-if="error"
      class="memory-graph__banner memory-graph__banner--negative bg-red-1 text-negative"
    >
      <template #avatar><q-icon name="error_outline" /></template>
      {{ t('memory.graph.loadError') }}
      <template #action>
        <q-btn flat color="negative" :label="t('memory.retry')" @click="reload" />
      </template>
    </q-banner>

    <q-banner
      v-if="edgesTruncated"
      class="memory-graph__banner memory-graph__banner--warning bg-orange-1 text-orange-10"
    >
      <template #avatar><q-icon name="filter_alt" /></template>
      {{ t('memory.graph.edgesTruncated') }}
    </q-banner>

    <q-banner v-if="threeUnavailable" class="memory-graph__banner memory-graph__banner--warning" role="status">
      {{ t('memory.graph.webglUnavailable') }}
      <template #action>
        <q-btn flat :label="t('memory.retry')" @click="retryRenderer" />
      </template>
    </q-banner>

    <q-banner v-if="viewStateError" class="memory-graph__banner memory-graph__banner--warning">
      {{ t('memory.graph.stateError') }}
      <template #action>
        <q-btn flat :label="t('memory.retry')" @click="retryViewState" />
      </template>
    </q-banner>

    <div
      v-if="agentId !== null"
      class="memory-graph__legend-panel"
      role="group"
      :aria-label="t('memory.graph.legend')"
    >

      <section class="memory-graph__legend-group">
        <div class="memory-graph__legend-title">{{ t('memory.graph.roleLegend') }}</div>
        <div class="memory-graph__legend-items">
          <q-btn
            v-for="role in GRAPH_ROLE_LEGEND"
            :key="role"
            flat
            dense
            no-caps
            class="memory-graph__legend-item memory-graph__type-filter"
            :class="{ 'memory-graph__type-filter--hidden': isEntityKindHidden(role) }"
            :aria-label="nodeTypeToggleLabel(t(`memory.graph.roles.${role}`), isEntityKindHidden(role))"
            :aria-pressed="!isEntityKindHidden(role)"
            @click="toggleEntityKind(role)"
          >
            <img
              v-if="role === 'folder' || role === 'directory'"
              :src="folderImageUrl(role)"
              width="16"
              height="16"
              alt=""
              :class="`memory-graph__role-symbol--${role}`"
            />
            <svg
              v-else-if="role === 'document' || role === 'attachment' || role === 'file'"
              viewBox="0 0 24 24"
              width="16"
              height="16"
              :class="`memory-graph__role-symbol--${role}`"
              aria-hidden="true"
              focusable="false"
            >
              <path :d="documentIconPath" :fill="roleColor(role)" />
            </svg>
            <span
              v-else
              class="memory-graph__role-symbol"
              :class="`memory-graph__role-symbol--${role}`"
              :style="{ backgroundColor: roleColor(role) }"
              aria-hidden="true"
            />
            {{ t(`memory.graph.roles.${role}`) }}
            <q-icon v-if="isEntityKindHidden(role)" name="visibility_off" size="12px" />
            <q-tooltip>
              {{ nodeTypeToggleLabel(t(`memory.graph.roles.${role}`), isEntityKindHidden(role)) }}
            </q-tooltip>
          </q-btn>
        </div>
      </section>

      <section class="memory-graph__legend-group memory-graph__legend-group--links">
        <div class="memory-graph__legend-title">{{ t('memory.graph.linkLegend') }}</div>
        <div class="memory-graph__legend-items memory-graph__legend-items--links">
          <span class="memory-graph__legend-item">
            <span
              class="memory-graph__link-legend-line"
              :style="{ borderTopColor: edgeColor('topic_contains') }"
              aria-hidden="true"
            />
            {{ t('memory.graph.topicMemoryLink') }}
          </span>
          <span class="memory-graph__legend-item">
            <span
              class="memory-graph__link-legend-line"
              :style="{ borderTopColor: edgeColor('contact_contains') }"
              aria-hidden="true"
            />
            {{ t('memory.graph.contactMemoryLink') }}
          </span>
          <span class="memory-graph__legend-item">
            <span
              class="memory-graph__link-legend-line"
              :style="{ borderTopColor: edgeColor('topic_involves_contact') }"
              aria-hidden="true"
            />
            {{ t('memory.graph.topicContactLink') }}
          </span>
          <span class="memory-graph__legend-item">
            <span
              class="memory-graph__link-legend-line memory-graph__link-legend-line--suggested"
              :style="{ borderTopColor: edgeColor('suggested') }"
              aria-hidden="true"
            />
            {{ t('memory.graph.suggestedLink') }}
          </span>
        </div>
      </section>

      <section class="memory-graph__legend-group memory-graph__legend-group--view">
        <div class="memory-graph__freshness-legend">
          <span class="memory-graph__freshness-endpoint">
            {{ t('memory.graph.older') }}
            <time v-if="activityExtent.oldest !== null" :datetime="new Date(activityExtent.oldest).toISOString()">
              {{ activityDateFormatter.format(activityExtent.oldest) }}
            </time>
          </span>
          <span class="memory-graph__freshness-samples" aria-hidden="true">
            <span
              v-for="score in [0, 0.5, 1]"
              :key="score"
              class="memory-graph__freshness-sample"
              :style="{
                width: `${NODE_MIN_RADIUS + score * NODE_RADIUS_RANGE}px`,
                height: `${NODE_MIN_RADIUS + score * NODE_RADIUS_RANGE}px`,
                opacity: MIN_NODE_OPACITY + score * (1 - MIN_NODE_OPACITY),
                backgroundColor: roleColor('memory'),
              }"
            />
          </span>
          <span class="memory-graph__freshness-endpoint">
            {{ t('memory.graph.recent') }}
            <time v-if="activityExtent.newest !== null" :datetime="new Date(activityExtent.newest).toISOString()">
              {{ activityDateFormatter.format(activityExtent.newest) }}
            </time>
          </span>
          <q-tooltip>{{ t('memory.graph.freshnessHint') }}</q-tooltip>
        </div>
        <GraphViewControls class="memory-graph__view-controls">
          <q-btn outline round dense color="primary" icon="add" :aria-label="t('memory.graph.zoomIn')" @click="zoomBy(1.25)">
            <q-tooltip>{{ t('memory.graph.zoomIn') }}</q-tooltip>
          </q-btn>
          <q-btn outline round dense color="primary" icon="remove" :aria-label="t('memory.graph.zoomOut')" @click="zoomBy(0.8)">
            <q-tooltip>{{ t('memory.graph.zoomOut') }}</q-tooltip>
          </q-btn>
          <q-btn outline round dense color="primary" icon="fit_screen" :aria-label="t('memory.graph.fit')" @click="fitGraph">
            <q-tooltip>{{ t('memory.graph.fit') }}</q-tooltip>
          </q-btn>
          <q-btn
            round
            dense
            color="primary"
            class="memory-graph__fullscreen-control"
            :class="{ 'memory-graph__fullscreen-control--active': isFullscreen }"
            :icon="isFullscreen ? 'fullscreen_exit' : 'fullscreen'"
            :aria-label="t(isFullscreen ? 'memory.graph.exitFullscreen' : 'memory.graph.fullscreen')"
            :aria-pressed="isFullscreen"
            @click="toggleFullscreen"
          >
            <q-tooltip>
              {{ t(isFullscreen ? 'memory.graph.exitFullscreen' : 'memory.graph.fullscreen') }}
            </q-tooltip>
          </q-btn>
        </GraphViewControls>
      </section>
    </div>

    <q-separator v-if="agentId !== null" class="memory-graph__legend-separator" />

    <div v-if="agentId !== null" class="memory-graph__layout">
      <div
        ref="viewport"
        class="memory-graph__viewport"
      >
        <div
          ref="threeElement"
          class="memory-graph__chart--3d"
          :class="{ 'memory-graph__chart--loading': graphBusy }"
          role="application"
          tabindex="0"
          :aria-label="t('memory.graph.canvas3dLabel')"
          :aria-description="t('memory.graph.navigation3d')"
        />
        <div v-if="!threeUnavailable && !graphBusy" class="memory-graph__navigation-hint">
          {{ t('memory.graph.navigation3d') }}
        </div>

        <div v-if="!threeUnavailable && !graphBusy && visibleNodes.length === 0" class="memory-graph__empty">
          <q-icon name="hub" size="48px" color="grey-5" />
          <div class="text-body2 text-grey-7 q-mt-sm">{{ t('memory.graph.empty') }}</div>
        </div>

        <q-inner-loading :showing="graphBusy">
          <q-spinner-orbit color="primary" size="42px" />
        </q-inner-loading>

        <q-dialog v-model="structuralDialog" :maximized="$q.screen.lt.md">
          <q-card v-if="selectedNode" class="memory-graph__detail galaris-dialog-card">
            <q-toolbar class="galaris-dialog-title">
              <q-icon :name="nodeIcon(selectedNode)" size="sm" class="q-mr-sm" />
              <q-toolbar-title>{{ selectedNode.title }}</q-toolbar-title>
              <q-btn flat round dense icon="close" :aria-label="t('memory.graph.closeDetails')" v-close-popup />
            </q-toolbar>
            <div class="galaris-dialog-body q-pa-md">
              <MemoryGraphNodeDetail
                :show-header="false"
                :agent-id="agentId"
                :node="selectedNode"
                :relations="selectedRelations"
                :color="roleColor(selectedNode.entity_kind)"
                :icon="nodeIcon(selectedNode)"
                :role-label="nodeRoleLabel(selectedNode)"
                @close="closeInspector"
                @open="selectNode"
                @select="selectNode"
              />
            </div>
          </q-card>
        </q-dialog>
      </div>
    </div>
  </q-card>
</template>

<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  shallowRef,
  useTemplateRef,
  watch,
} from 'vue'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import { websocket } from '@/core/websocket'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration, SupersededSessionError } from '@/core/api'
import { GraphViewControls, browserResourceKind, solaire, solaireCss, type BrowserResourceKind, type SolaireColor } from '@/core/util'
import { useInterval, useQuasar, useTimeout } from 'quasar'
import { matAudioFile, matDescription, matImage, matVideoFile } from '@quasar/extras/material-icons'
import MemoryGraphNodeDetail from './MemoryGraphNodeDetail.vue'
import { memoryService } from '../services/memoryService'
import { graphBranches, GraphBranchLayout, BRANCH_OPEN_ZOOM, BRANCH_CLOSE_ZOOM } from '../graphBranches'
import { GraphThumbnails, type GraphThumbnailCandidate } from '../graphThumbnails'
import { onThumbnailReady } from '../thumbnailEvents'
import { GraphStatePersistence, type GraphPreferences, type GraphContext } from '../graphState'
import type { MemoryGraphScene, Graph3dCamera, Graph3dPreview } from '../graph3dScene'
import type { Graph3dLayoutResult, GraphPoint3d } from '../graph3dLayout'
import { graphNodeLevel } from '../graph3dHierarchy'
import { Graph3dChildren } from '../graph3dChildren'
import { graphHiddenItems } from '../graphVisibility'
import { reconcileGraph } from '../graphRefresh'
import type {
  CatalogueResource,
  MemoryGraphCursor,
  MemoryGraphEdge,
  MemoryGraphEntityKind,
  MemoryGraphNode,
  MemoryGraphPage,
  MemoryGraphRelation,
} from '../types'

const {
  agentId,
  query,
  topicItemId,
  contactItemId,
} = defineProps<{
  agentId: number | null
  query: string
  topicItemId: string | null
  contactItemId: string | null
}>()

const emit = defineEmits<{
  open: [id: string, node: MemoryGraphNode, relations: MemoryGraphRelation[]]
}>()

const ROOT_PAGE_SIZE = 500
const AUTO_REFRESH_INTERVAL = 5 * 60_000
const LINK_WIDTH_SCALE = 0.8
const NODE_MIN_RADIUS = 10
const NODE_RADIUS_RANGE = 8
const MIN_NODE_OPACITY = 0.4
const GRAPH_ROLE_LEGEND: readonly MemoryGraphEntityKind[] = [
  'memory',
  'topic',
  'contact',
  'document',
  'attachment',
  'folder',
  'file',
  'directory',
  'conversation',
]
const RESOURCE_ROLE_ACCENTS: Partial<Record<MemoryGraphEntityKind, 'yellow' | 'orange' | 'gray'>> = {
  attachment: 'gray',
  file: 'gray',
  folder: 'yellow',
  directory: 'orange',
}

const { t, locale } = useI18n()
const $q = useQuasar()
const { registerInterval, removeInterval } = useInterval()
const { registerTimeout: registerThumbnailTimeout, removeTimeout: removeThumbnailTimeout } = useTimeout()
const { registerTimeout: registerSaveTimeout, removeTimeout: removeSaveTimeout } = useTimeout()
const viewport = useTemplateRef<HTMLDivElement>('viewport')
const threeElement = useTemplateRef<HTMLDivElement>('threeElement')
const spatialGroupedCount = ref(0)
const spatialHiddenCount = ref(0)
const threeUnavailable = ref(false)
let threeScene: MemoryGraphScene | null = null
let threeCamera: Graph3dCamera | null = null
let threeInitializing: Promise<void> | null = null
let threeWorker: Worker | null = null
let cancelThreeLayout: (() => void) | null = null
let threeLayout: Promise<Graph3dLayoutResult | null> | null = null
let threeLayoutKey: unknown[] = []
let threePoints = new Map<string, GraphPoint3d>()
let threeRenderGeneration = 0
let threeDisposed = false
const threeHasMap = ref(false)
let threeChildren: Graph3dChildren | null = null
let resourceBranches: Record<string, number> = {}
const nodes = shallowRef(new Map<string, MemoryGraphNode>())
const edges = shallowRef(new Map<string, MemoryGraphEdge>())
const expandedBranches = shallowRef(new Set<string>())
const branchLayout = new GraphBranchLayout()
const filteredLayout = new GraphBranchLayout()
const dynamicLayout = computed(() => nodes.value.size <= 600)
const hiddenEntityKinds = shallowRef(new Set<MemoryGraphEntityKind>())
const viewStateError = ref<unknown>(null)
let persistence: GraphStatePersistence | null = null
let graphSession = sessionGeneration()
const selectedNodeId = ref<string | null>(null)
const edgesTruncated = ref(false)
const loading = ref(false)
const reloading = ref(false)
const refreshing = ref(false)
let refreshAgain = false
const liveRefresh = ref(true)
const error = ref<unknown>(null)
const isFullscreen = ref(false)
const layoutPending = ref(false)
const chartReady = ref(false)
const viewportSize = reactive({ width: 0, height: 0 })

let resizeObserver: ResizeObserver | null = null
let previousBodyOverflow: string | null = null
let loadGeneration = 0
let rootController: AbortController | null = null
let thumbnailFrame: number | null = null
let thumbnailPaintTimer: ReturnType<typeof setTimeout> | null = null
const thumbnailBudget = clientThumbnailBudget()
const thumbnailKeys = new Map<string, string>()
const thumbnailResources = new Map<string, CatalogueResource>()
const thumbnails = new GraphThumbnails(
  (node, signal, generate) => agentId === null ? Promise.resolve(null)
    : memoryService.graphFileThumbnail(node, agentId, signal, generate, thumbnailResources),
  missing => {
    scheduleThumbnailPaint()
    if (missing) scheduleThumbnails()
  },
  thumbnailBudget * 2,
  thumbnailBudget >= 1024 ? 24 : thumbnailBudget >= 256 ? 12 : thumbnailBudget >= 96 ? 8 : 4,
)
const unsubscribeThumbnailReady = onThumbnailReady(ready => {
  if (ready.agentId !== agentId) return
  for (const node of nodes.value.values()) {
    if (((node.node_kind === 'file' || node.node_kind === 'document') && node.id === ready.itemId)
      || (node.node_kind === 'attachment' && node.resource_uri === ready.resourceUri)) {
      thumbnails.accept({ node, key: thumbnailKey(node) }, ready.blob)
    }
  }
})

const visibleNodes = computed(() => (
  [...nodes.value.values()].filter(isNodeVisible)
))
const visibleNodeIds = computed(() => new Set(visibleNodes.value.map(node => node.id)))
const visibleEdges = computed(() => (
  [...edges.value.values()].filter(edge => (
    visibleNodeIds.value.has(edge.source_item_id)
    && visibleNodeIds.value.has(edge.target_item_id)
  ))
))
const branches = computed(() => {
  // Subtract only known, hidden neighbors. Unknown off-page neighbors must
  // still prevent grouping, while hiding contacts can reveal topic branches.
  const hiddenNeighbors = new Map<string, Set<string>>()
  for (const edge of edges.value.values()) {
    for (const [id, other] of [[edge.source_item_id, edge.target_item_id], [edge.target_item_id, edge.source_item_id]]) {
      if (!id || !other || !visibleNodeIds.value.has(id) || !nodes.value.has(other) || visibleNodeIds.value.has(other)) continue
      if (!hiddenNeighbors.has(id)) hiddenNeighbors.set(id, new Set())
      hiddenNeighbors.get(id)!.add(other)
    }
  }
  return graphBranches(visibleNodes.value.map(node => ({ ...node,
    relation_count: node.relation_count - (hiddenNeighbors.get(node.id)?.size ?? 0),
  })), visibleEdges.value)
})
const branchByAnchor = computed(() => new Map(branches.value.map(branch => [branch.anchorId, branch])))
const layoutSignature = computed(() => JSON.stringify({
  nodes: visibleNodes.value.map(node => [node.id, node.entity_kind, node.resource_uri, node.relation_count]),
  edges: visibleEdges.value.map(edge => [edge.id, edge.source_item_id, edge.target_item_id, edge.relation_type, edge.suggested]),
}))
const collapsedMemberIds = computed(() => new Set(branches.value
  .filter(branch => !expandedBranches.value.has(branch.anchorId))
  .flatMap(branch => branch.memberIds.filter(id => id !== selectedNodeId.value))))
const groupedNodeCount = computed(() => collapsedMemberIds.value.size + spatialGroupedCount.value)
const renderedNodes = computed(() => visibleNodes.value.filter(node => !collapsedMemberIds.value.has(node.id)))
const hiddenRepresentatives = computed(() => new Map(branches.value.flatMap(branch => branch.memberIds
  .filter(id => collapsedMemberIds.value.has(id)).map(id => [id, branch.anchorId] as const))))
const hiddenItems = computed(() => graphHiddenItems(
  [...nodes.value.values()], [...edges.value.values()],
  new Set(renderedNodes.value.map(node => node.id)),
  hiddenRepresentatives.value,
))
const hiddenNodeCount = computed(() => threeHasMap.value
  ? spatialHiddenCount.value : hiddenItems.value.hiddenCount)
const directoriesWithUnloadedChildren = computed(() => {
  const children = new Map<string, Set<string>>()
  for (const edge of edges.value.values()) {
    if (edge.suggested || edge.relation_type !== 'parent_of' || !nodes.value.has(edge.target_item_id)) continue
    if (!children.has(edge.source_item_id)) children.set(edge.source_item_id, new Set())
    children.get(edge.source_item_id)!.add(edge.target_item_id)
  }
  return new Set([...nodes.value.values()].filter(node => node.entity_kind === 'directory'
    && (node.children_count ?? 0) > (children.get(node.id)?.size ?? 0)).map(node => node.id))
})
const renderedEdges = computed(() => visibleEdges.value.filter(edge => (
  !collapsedMemberIds.value.has(edge.source_item_id) && !collapsedMemberIds.value.has(edge.target_item_id)
)))
const selectedNode = computed(() => {
  if (selectedNodeId.value === null) return null
  const node = nodes.value.get(selectedNodeId.value)
  return node && isNodeVisible(node) ? node : null
})

const graphBusy = computed(() => !threeUnavailable.value && !threeHasMap.value
  && (loading.value || layoutPending.value || !chartReady.value))
const structuralDialog = computed({
  get: () => selectedNode.value?.node_kind === 'folder' || selectedNode.value?.node_kind === 'conversation',
  set: (open: boolean) => { if (!open) closeInspector() },
})

const activityExtent = computed(() => {
  const timestamps = [...nodes.value.values()]
    .map(activityTimestamp)
    .filter(Number.isFinite)
  return {
    newest: timestamps.length ? timestamps.reduce((left, right) => Math.max(left, right)) : null,
    oldest: timestamps.length ? timestamps.reduce((left, right) => Math.min(left, right)) : null,
  }
})
const activityDateFormatter = computed(() => new Intl.DateTimeFormat(locale.value, { dateStyle: 'short' }))

const selectedRelations = computed<MemoryGraphRelation[]>(() => {
  if (selectedNodeId.value === null) return []
  const relations: MemoryGraphRelation[] = []
  for (const edge of visibleEdges.value) {
    let otherId: string | null = null
    if (edge.source_item_id === selectedNodeId.value) otherId = edge.target_item_id
    if (edge.target_item_id === selectedNodeId.value) otherId = edge.source_item_id
    if (otherId === null) continue
    const other = nodes.value.get(otherId)
    if (other) relations.push({ edge, other })
  }
  return relations.sort((left, right) => left.edge.relation_type.localeCompare(right.edge.relation_type))
})


function roleAccent(role: MemoryGraphEntityKind): SolaireColor {
  const accent = RESOURCE_ROLE_ACCENTS[role]
  if (accent) return accent
  switch (role) {
    case 'memory': return 'green'
    case 'topic': return 'blue'
    case 'contact': return 'fuchsia'
    case 'document': return 'red'
    case 'conversation': return 'iris'
    default: return 'green'
  }
}


function roleColor(role: MemoryGraphEntityKind): string {
  return solaireCss[roleAccent(role)].accent
}

function isEntityKindHidden(kind: MemoryGraphEntityKind): boolean {
  return hiddenEntityKinds.value.has(kind)
}

function isNodeVisible(node: MemoryGraphNode): boolean {
  return !isEntityKindHidden(node.entity_kind)
}

function nodeTypeToggleLabel(label: string, hidden: boolean): string {
  return t(hidden ? 'memory.graph.showNodeType' : 'memory.graph.hideNodeType', { type: label })
}

function renderTypeFilterChange(): void {
  if (selectedNodeId.value !== null && selectedNode.value === null) closeInspector()
  filteredLayout.clear()
  expandedBranches.value = new Set()
  void renderGraph3d(true)
}

function toggleEntityKind(kind: MemoryGraphEntityKind): void {
  const next = new Set(hiddenEntityKinds.value)
  if (next.has(kind)) next.delete(kind)
  else next.add(kind)
  hiddenEntityKinds.value = next
  persistence?.stagePreferences({ hidden_entity_kinds: [...next] })
  scheduleViewSave()
  renderTypeFilterChange()
}

function nodeIcon(node: MemoryGraphNode): string {
  const resourceKind = nodeResourceKind(node)
  if (resourceKind === 'audio') return 'audio_file'
  if (resourceKind === 'image') return 'image'
  if (resourceKind === 'video') return 'video_file'
  switch (node.entity_kind) {
    case 'topic': return 'topic'
    case 'contact': return 'person'
    case 'document': return 'description'
    case 'attachment': return 'attach_file'
    case 'folder': return 'folder'
    case 'file': return 'insert_drive_file'
    case 'directory': return 'folder_open'
    case 'conversation': return 'forum'
    default: return 'neurology'
  }
}

function nodeRoleLabel(node: MemoryGraphNode): string {
  return t(`memory.graph.roles.${node.entity_kind}`)
}

function nodeResourceKind(node: MemoryGraphNode): BrowserResourceKind | null {
  if (node.node_kind !== 'file' && node.node_kind !== 'attachment') return null
  const resource = thumbnailResources.get(`${node.id}:${node.updated_at ?? node.activity_at}`)
  return browserResourceKind(resource?.media_type ?? node.resource_media_type ?? '', resource?.name ?? node.title)
}

function isAudioNode(node: MemoryGraphNode): boolean {
  return nodeResourceKind(node) === 'audio'
}

function folderImageUrl(role: MemoryGraphEntityKind): string {
  return `/folder-icons/gnome/${roleAccent(role)}/folder.svg`
}
// Material icons include a transparent viewport path before the visible artwork.
const documentIconPath = matDescription.split('&&').at(-1) ?? ''
const documentSymbol = `path://${documentIconPath}`
const mediaFileSymbols = {
  audio: `path://${matAudioFile.split('&&').at(-1) ?? ''}`,
  image: `path://${matImage.split('&&').at(-1) ?? ''}`,
  video: `path://${matVideoFile.split('&&').at(-1) ?? ''}`,
}

function nodeSymbol(node: MemoryGraphNode): string {
  const resourceKind = nodeResourceKind(node)
  if (resourceKind === 'audio') return mediaFileSymbols.audio
  if (resourceKind === 'image' || resourceKind === 'video') return mediaFileSymbols[resourceKind]
  switch (node.entity_kind) {
    case 'topic': return 'diamond'
    case 'contact': return 'roundRect'
    case 'document': return documentSymbol
    case 'attachment': return documentSymbol
    case 'folder': return `image://${folderImageUrl(node.entity_kind)}`
    case 'file': return documentSymbol
    case 'directory': return `image://${folderImageUrl(node.entity_kind)}`
    case 'conversation': return 'roundRect'
    default: return 'circle'
  }
}

function nodeBaseSymbolSize(node: MemoryGraphNode): number {
  const scale = dynamicLayout.value ? Math.min(1, Math.max(0.35, Math.min(viewportSize.width, viewportSize.height) / 650)) : 1
  return Math.min(48, radiusFor(node) * 2 * scale)
}

function clientThumbnailBudget(): number {
  const memory: unknown = Reflect.get(navigator, 'deviceMemory')
  // This is an approximate, possibly capped hint; absence does not imply low RAM.
  const gigabytes = typeof memory === 'number' && memory > 0 ? memory : null
  const cores = navigator.hardwareConcurrency || 4
  const limited = (gigabytes !== null && gigabytes <= 2) || cores <= 2
  if (window.innerWidth < 1024) return limited ? 32 : 96
  // Browser memory hints can underestimate powerful desktops; they must not cap a directory at 64 images.
  // A 320px derivative has four times the pixel budget of the former 160px copy.
  return cores >= 8 ? 256 : 128
}

function isStructuralNode(node: MemoryGraphNode): boolean {
  return node.entity_kind === 'topic' || node.entity_kind === 'contact'
}

function edgeColor(relationType: string): string {
  return solaireCss[edgeAccent(relationType)].accent
}

function edgeAccent(relationType: string): SolaireColor {
  if (relationType === 'topic_involves_contact') return 'violet'
  if (relationType === 'contact_contains') return 'fuchsia'
  if (relationType === 'topic_contains' || relationType.startsWith('topic_')) return 'green'
  return 'gray'
}

function isStructuralEdge(relationType: string): boolean {
  return relationType === 'topic_contains'
    || relationType === 'contact_contains'
    || relationType === 'topic_involves_contact'
}

function reducedLinkWidth(width: number): number {
  return width <= 1 ? width : Math.max(1, width * 0.8 * 0.7)
}

function nodePaintStyle(node: MemoryGraphNode, selected: boolean, palette: CSSStyleDeclaration) {
  const geometric = ['memory', 'topic', 'contact', 'conversation'].includes(node.entity_kind)
  const hideBorder = ['folder', 'directory', 'file', 'attachment'].includes(node.entity_kind)
  return {
    color: palette.getPropertyValue(`--solaire-${roleAccent(node.entity_kind)}-accent`).trim(),
    opacity: selected ? 1 : MIN_NODE_OPACITY + freshness(node) * (1 - MIN_NODE_OPACITY),
    borderColor: geometric ? palette.getPropertyValue(`--solaire-${roleAccent(node.entity_kind)}-dark`).trim()
      : selected || isStructuralNode(node) ? ($q.dark.isActive ? '#ffffff' : '#263238')
        : node.source_managed ? '#90caf9' : 'rgba(255, 255, 255, 0.9)',
    borderWidth: hideBorder ? 0 : selected ? 4 : geometric ? 2 : node.source_managed ? 2 : 1.5,
  }
}

function edgePaintStyle(edge: MemoryGraphEdge, overviewMode: boolean, opacityScale: number, palette: CSSStyleDeclaration) {
  return {
    color: palette.getPropertyValue(`--solaire-${edgeAccent(edge.relation_type)}-accent`).trim(),
    opacity: (overviewMode ? 0.5 : edge.suggested ? 0.38 : isStructuralEdge(edge.relation_type) ? 0.86 : 0.62) * opacityScale,
    width: reducedLinkWidth((overviewMode ? 0.5 : edge.suggested ? 0.8 + edge.confidence
      : isStructuralEdge(edge.relation_type) ? 2 + edge.confidence * 1.8 : 0.9 + edge.confidence * 1.4) * LINK_WIDTH_SCALE),
    type: edge.suggested ? 'dashed' as const : 'solid' as const,
  }
}

function activityTimestamp(node: MemoryGraphNode): number {
  const timestamp = Date.parse(node.activity_at)
  return Number.isFinite(timestamp) ? timestamp : Date.parse(node.created_at)
}

function freshness(node: MemoryGraphNode): number {
  const timestamp = activityTimestamp(node)
  const { newest, oldest } = activityExtent.value
  if (!Number.isFinite(timestamp) || newest === null || oldest === null || newest <= oldest) return 1
  return Math.max(0, Math.min(1, (timestamp - oldest) / (newest - oldest)))
}

function radiusFor(node: MemoryGraphNode): number {
  const roleBoost = node.entity_kind === 'topic'
    ? 6
    : node.entity_kind === 'contact'
      ? 4
      : node.entity_kind === 'document'
        ? 2
        : 0
  return NODE_MIN_RADIUS + freshness(node) * NODE_RADIUS_RANGE + roleBoost + (selectedNodeId.value === node.id ? 3 : 0)
}

function revealBranch(id: string): void {
  expandedBranches.value = new Set([...expandedBranches.value, id])
  persistence?.stagePreferences({ expanded_branches: [...expandedBranches.value] })
  scheduleViewSave()
  void renderGraph3d().then(() => threeScene?.focus(id))
}

function thumbnailKey(node: MemoryGraphNode): string {
  return `${agentId}:${node.id}:${node.updated_at ?? node.activity_at}:${node.resource_uri ?? ''}`
}

function scheduleThumbnails(): void {
  registerThumbnailTimeout(updateThreeThumbnails, 120)
}

function scheduleThumbnailPaint(): void {
  if (thumbnailFrame !== null || thumbnailPaintTimer !== null) return
  thumbnailPaintTimer = setTimeout(() => {
    thumbnailPaintTimer = null
    thumbnailFrame = requestAnimationFrame(paintThumbnails)
  }, 80)
}

function paintThumbnails(): void {
  thumbnailFrame = null
  paintThreeThumbnails()
}

function mergeNodes(incoming: MemoryGraphNode[]): string[] {
  let next = nodes.value
  const addedIds: string[] = []
  for (const node of incoming) {
    const existing = next.get(node.id)
    if (existing && JSON.stringify(existing) === JSON.stringify(node)) continue
    if (next === nodes.value) next = new Map(next)
    if (existing) {
      next.set(node.id, node)
      continue
    }
    next.set(node.id, node)
    addedIds.push(node.id)
  }
  nodes.value = next
  return addedIds
}

function mergeEdges(incoming: MemoryGraphEdge[]): void {
  let next = edges.value
  for (const edge of incoming) {
    if (!nodes.value.has(edge.source_item_id) || !nodes.value.has(edge.target_item_id)) continue
    if (JSON.stringify(next.get(edge.id)) === JSON.stringify(edge)) continue
    if (next === edges.value) next = new Map(next)
    next.set(edge.id, edge)
  }
  edges.value = next
}

function mergeRootPage(page: MemoryGraphPage): void {
  if (page.positions && persistence?.restoresPositions !== false) {
    for (const [key, point] of Object.entries(page.positions)) {
      branchLayout.positions.set(key, { x: point[0], y: point[1] })
    }
    persistence?.remember(Object.entries(page.positions).map(([key, point]) => [key, { x: point[0], y: point[1] }]))
  }
  mergeNodes(page.nodes)
  mergeEdges(page.edges)
  edgesTruncated.value = edgesTruncated.value || page.edges_truncated
}

function parallelEdgeCurvatures(): Map<string, number> {
  const groups = new Map<string, MemoryGraphEdge[]>()
  for (const edge of visibleEdges.value) {
    const pairKey = edge.source_item_id < edge.target_item_id
      ? `${edge.source_item_id}:${edge.target_item_id}`
      : `${edge.target_item_id}:${edge.source_item_id}`
    const groupedEdges = groups.get(pairKey) ?? []
    groupedEdges.push(edge)
    groups.set(pairKey, groupedEdges)
  }
  const curvatures = new Map<string, number>()
  for (const groupedEdges of groups.values()) {
    groupedEdges.sort((left, right) => left.id.localeCompare(right.id))
    if (groupedEdges.length === 1 && groupedEdges[0]) {
      curvatures.set(groupedEdges[0].id, 0.22)
      continue
    }
    const center = (groupedEdges.length - 1) / 2
    for (const [index, edge] of groupedEdges.entries()) {
      let curvature = (index - center) * 0.16
      if (Math.abs(curvature) < 0.04) curvature = 0.1
      curvatures.set(edge.id, curvature)
    }
  }
  return curvatures
}

function applyPreferences(preferences: GraphPreferences): void {
  hiddenEntityKinds.value = new Set(preferences.hidden_entity_kinds)
  expandedBranches.value = new Set(preferences.expanded_branches)
  threeCamera = preferences.camera_3d ?? null
  resourceBranches = { ...preferences.resource_branches }
}

function stagePositions(): void {
  if (!persistence || !chartReady.value) return
  persistence.stagePositions(branchLayout.positions)
}

function scheduleViewSave(): void {
  registerSaveTimeout(() => { void persistence?.flush() }, 600)
}

function stagePresentation(): void {
  if (persistence && threeScene && threeHasMap.value && !loading.value && !reloading.value) {
    threeCamera = threeScene.view
    persistence.stagePreferences({ expanded_branches: [...expandedBranches.value], camera_3d: threeCamera,
      resource_branches: { ...resourceBranches } })
    scheduleViewSave()
  }
}

async function retryViewState(): Promise<void> {
  const current = persistence
  if (!current) return
  try {
    if (threeHasMap.value) {
      current.stagePreferences({ hidden_entity_kinds: [...hiddenEntityKinds.value] })
      stagePresentation()
    }
    await current.flush()
  } catch (failure) {
    if (current === persistence) viewStateError.value = failure
  }
}

function renderGraph(): void {
  void renderGraph3d()
}

async function loadInitial(options: { preserveView?: boolean } = {}): Promise<void> {
  const preserveView = options.preserveView === true
  const preservedSelection = preserveView ? selectedNodeId.value : null
  if (preserveView && threeScene && threeHasMap.value) threeCamera = threeScene.view
  if (!preserveView) {
    stagePresentation()
    void persistence?.flush()
    removeSaveTimeout()
    persistence = null
  }
  const generation = ++loadGeneration
  refreshing.value = false
  refreshAgain = false
  rootController?.abort()
  threeChildren?.dispose()
  threeChildren = null
  const controller = new AbortController()
  rootController = controller
  thumbnails.clear()
  threeScene?.setPreviews(new Map())
  threeScene?.setData([], [], [], false, { nodes: [], edges: [], representatives: new Map() })
  spatialHiddenCount.value = 0
  cancelThreeLayout?.()
  threeLayout = null
  threeLayoutKey = []
  threePoints.clear()
  spatialGroupedCount.value = 0
  threeHasMap.value = false
  threeRenderGeneration++
  thumbnailResources.clear()
  thumbnailKeys.clear()
  removeThumbnailTimeout()
  nodes.value = new Map()
  edges.value = new Map()
  selectedNodeId.value = preservedSelection
  edgesTruncated.value = false
  error.value = null
  if (!preserveView) chartReady.value = agentId === null
  if (!preserveView) {
    branchLayout.clear()
    filteredLayout.clear()
    hiddenEntityKinds.value = new Set()
    threeCamera = null
    viewStateError.value = null
    expandedBranches.value = new Set()
    resourceBranches = {}
  }
  layoutPending.value = false
  if (agentId === null) {
    threeScene?.dispose()
    threeScene = null
    loading.value = false
    reloading.value = false
    return
  }

  if (preserveView) {
    reloading.value = true
  } else {
    loading.value = true
  }
  try {
    if (!preserveView) {
      const context: GraphContext = { agent_id: agentId, query, topic_item_id: topicItemId, contact_item_id: contactItemId }
      const session = sessionGeneration()
      const transport = {
        readGraphState: (context: GraphContext) => {
          if (session !== sessionGeneration()) return Promise.reject(new SupersededSessionError())
          return memoryService.readGraphState(context)
        },
        saveGraphState: (context: GraphContext, patch: import('../graphState').GraphStatePatch) => {
          if (session !== sessionGeneration()) return Promise.reject(new SupersededSessionError())
          return memoryService.saveGraphState(context, patch)
        },
      }
      const current = new GraphStatePersistence(context, transport, positions => {
        if (persistence !== current) return
        for (const [key, point] of Object.entries(positions)) if (nodes.value.has(key)) branchLayout.positions.set(key, point)
      }, failure => { if (persistence === current) viewStateError.value = failure })
      persistence = current
      try {
        const preferences = await current.load()
        if (generation !== loadGeneration) return
        applyPreferences(preferences)
      } catch (failure) {
        if (generation !== loadGeneration) return
        viewStateError.value = failure
      }
    }
    let cursor: MemoryGraphCursor | null = null
    let loadNextPage = true
    const restoredResources = Object.entries(resourceBranches)
    const savedThreeCamera = restoredResources.length ? threeCamera : null
    if (savedThreeCamera) threeCamera = null
    const context = { agentId, query, topicItemId, contactItemId }
    const regions = new Graph3dChildren(
      (itemId, cursor, signal) => memoryService.expandGraphNode({ ...context, itemId, cursor, signal,
        limit: ROOT_PAGE_SIZE, childrenOnly: true }),
      async page => {
        if (generation !== loadGeneration || threeDisposed) return
        mergeRootPage(page)
        await renderGraph3d()
      },
      caught => {
        if (generation !== loadGeneration) return
        regions.update([], '')
        error.value = caught
      },
      () => {
        if (generation !== loadGeneration) return
        resourceBranches = regions.expanded
        stagePresentation()
      },
    )
    threeChildren = regions
    while (loadNextPage) {
      const page = await memoryService.listGraphRoots({
        ...context,
        limit: ROOT_PAGE_SIZE,
        edgeLimit: 10_000,
        orderBy: 'hierarchy',
        deferResourceFiles: true,
        cursor,
        includeMatchingRoots: true,
        includeSavedPositions: true,
        signal: controller.signal,
      })
      if (generation !== loadGeneration) return
      mergeRootPage(page)
      loadNextPage = page.has_more && page.next_cursor !== null
      cursor = page.next_cursor
      {
        await nextTick()
        await initializeRenderer()
        if (generation !== loadGeneration) return
        await renderGraph3d()
        if (generation !== loadGeneration) return
        // Yield for the first visible frame before fetching the next page.
        // Only one placement worker runs at a time; retain reached positions.
        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
      }
    }
    for (const [id, pages] of restoredResources) {
      for (let page = 0; page < pages; page++) {
        if (generation !== loadGeneration || error.value) return
        await regions.load(id, `restore-${page}`)
      }
    }
    if (savedThreeCamera && generation === loadGeneration) {
      threeCamera = savedThreeCamera
      threeScene?.restore(savedThreeCamera)
    }
    if (selectedNodeId.value !== null && !nodes.value.has(selectedNodeId.value)) {
      selectedNodeId.value = null
    }
    await nextTick()
    await initializeRenderer()
    renderGraph()
  } catch (caught) {
    if (generation === loadGeneration) {
      error.value = caught
      layoutPending.value = false
      chartReady.value = true
    }
  } finally {
    if (generation === loadGeneration) {
      loading.value = false
      reloading.value = false
      stagePresentation()
      onThreeCamera()
    }
  }
}

function reload(): void {
  void loadInitial({ preserveView: true })
}

function invalidateAccess(): void {
  stagePresentation()
  nodes.value = new Map()
  edges.value = new Map()
  closeInspector()
  void loadInitial()
}

function onGraphSessionChange(): void {
  const session = sessionGeneration()
  if (session === graphSession) return
  graphSession = session
  persistence = null
  viewStateError.value = null
  removeSaveTimeout()
  invalidateAccess()
}

function onGraphReconnect(): void { void refreshLatestRoots(true) }

async function refreshLatestRoots(force = false): Promise<void> {
  if (
    (!force && !liveRefresh.value)
    || agentId === null
    || loading.value
    || reloading.value
    || document.visibilityState !== 'visible'
  ) return
  if (refreshing.value) { refreshAgain = refreshAgain || force; return }
  const generation = loadGeneration
  const context = { agentId, query, topicItemId, contactItemId, signal: rootController?.signal }
  const baseline = { nodes: nodes.value, edges: edges.value }
  const snapshot = { nodes: new Map<string, MemoryGraphNode>(), edges: new Map<string, MemoryGraphEdge>() }
  const visited = threeChildren?.expanded ?? {}
  const completed = threeChildren?.completed ?? new Set<string>()
  const regions = new Map<string, number>()
  let truncated = false
  const collect = (page: MemoryGraphPage): void => {
    for (const node of page.nodes) snapshot.nodes.set(node.id, node)
    for (const edge of page.edges) snapshot.edges.set(edge.id, edge)
    truncated = truncated || page.edges_truncated === true
  }
  refreshing.value = true
  try {
    let cursor: MemoryGraphCursor | null = null
    do {
      const page = await memoryService.listGraphRoots({ ...context, limit: ROOT_PAGE_SIZE,
        edgeLimit: 10_000, orderBy: 'hierarchy', deferResourceFiles: true, includeMatchingRoots: true, cursor })
      if (generation !== loadGeneration) return
      collect(page)
      cursor = page.has_more ? page.next_cursor : null
    } while (cursor)
    for (const id of completed) {
      if (!snapshot.nodes.has(id)) continue
      let pages = 0
      cursor = null
      do {
        let page: MemoryGraphPage
        try {
          page = await memoryService.expandGraphNode({ ...context, itemId: id, cursor,
            limit: ROOT_PAGE_SIZE, childrenOnly: true })
        } catch (failure) {
          if (!isAxiosError(failure) || failure.response?.status !== 404) throw failure
          snapshot.nodes.delete(id)
          break
        }
        if (generation !== loadGeneration) return
        collect(page)
        pages++
        cursor = page.has_more ? page.next_cursor : null
      } while (cursor)
      if (snapshot.nodes.has(id)) regions.set(id, pages)
    }
    // An incomplete region has no authoritative inventory yet. Keep its reached
    // files; the foreground loader continues from its own cursor independently.
    for (const edge of baseline.edges.values()) {
      if (edge.relation_type !== 'parent_of' || completed.has(edge.source_item_id)
        || !visited[edge.source_item_id] || !snapshot.nodes.has(edge.source_item_id)) continue
      const child = baseline.nodes.get(edge.target_item_id)
      if (!child || child.entity_kind === 'directory') continue
      if (!snapshot.nodes.has(child.id)) snapshot.nodes.set(child.id, child)
      snapshot.edges.set(edge.id, edge)
    }
    if (generation !== loadGeneration || threeDisposed) return
    const current = { nodes: nodes.value, edges: edges.value }
    const next = reconcileGraph(current, baseline, snapshot, truncated)
    for (const id of current.nodes.keys()) if (!next.nodes.has(id)) {
      threeChildren?.forget(id)
      thumbnailResources.delete(id)
    }
    for (const [id, pages] of regions) threeChildren?.reconcile(id, visited[id]!, null, pages)
    resourceBranches = threeChildren?.expanded ?? {}
    edgesTruncated.value = truncated
    if (next.nodes === current.nodes && next.edges === current.edges) return
    nodes.value = next.nodes
    edges.value = next.edges
    if (selectedNodeId.value && !nodes.value.has(selectedNodeId.value)) closeInspector(false)
    await renderGraph3d(false, true)
  } catch (failure) {
    if (generation === loadGeneration && isAxiosError(failure)
      && [401, 403].includes(failure.response?.status ?? 0)) invalidateAccess()
    // The regular reload button owns visible error reporting.
  } finally {
    if (generation === loadGeneration) {
      refreshing.value = false
      stagePresentation()
      if (refreshAgain) { refreshAgain = false; void refreshLatestRoots(true) }
    }
  }
}

function selectNode(id: string): void {
  const node = nodes.value.get(id)
  if (!node || !isNodeVisible(node)) return
  selectedNodeId.value = id
  threeScene?.setSelected(id)
  void renderGraph3d().then(() => threeScene?.focus(id))
  if (node.node_kind !== 'folder' && node.node_kind !== 'conversation') {
    emit('open', id, node, selectedRelations.value)
  }
}

function closeInspector(render = true): void {
  if (selectedNodeId.value === null) return
  selectedNodeId.value = null
  threeScene?.setSelected(null)
  if (render) renderGraph()
}

defineExpose({ selectNode, closeDetails: closeInspector })

function resizeChart(): void {
  const container = viewport.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  viewportSize.width = Math.max(1, Math.floor(rect.width))
  viewportSize.height = Math.max(1, Math.floor(rect.height))
  threeScene?.resize()
  scheduleThumbnails()
}

function fitGraph(): void {
  expandedBranches.value = new Set()
  closeInspector(false)
  void renderGraph3d().then(() => threeScene?.fit())
}

async function resetPositions(): Promise<void> {
  if (!persistence || !threeScene || loading.value || reloading.value || layoutPending.value) return
  const current = persistence
  removeSaveTimeout()
  current.resetPositions({ hidden_entity_kinds: [...hiddenEntityKinds.value], resource_branches: { ...resourceBranches } })
  branchLayout.clear()
  filteredLayout.clear()
  threePoints.clear()
  threeLayoutKey = []
  threeCamera = null
  threeHasMap.value = false
  expandedBranches.value = new Set()
  closeInspector(false)
  await renderGraph3d(true)
  if (persistence !== current) return
  stagePresentation()
  scheduleViewSave()
}

function zoomBy(scaleFactor: number): void {
  threeScene?.zoomBy(scaleFactor)
}

async function initializeRenderer(): Promise<void> {
  if (threeDisposed || agentId === null) return
  resizeObserver?.disconnect()
  if (viewport.value) resizeObserver?.observe(viewport.value)
  if (threeScene) return
  if (threeInitializing) return threeInitializing
  threeInitializing = (async () => {
    try {
      const { MemoryGraphScene } = await import('../graph3dScene')
      if (threeDisposed || !threeElement.value) return
      threeScene = new MemoryGraphScene(threeElement.value, {
        groupTitle: count => t('memory.graph.spatialGroup', { count }),
        hiddenTitle: (title, count, compact = false) => `${title} (${t(compact ? 'memory.graph.hiddenBadge' : 'memory.graph.hiddenRelated', { count })})`,
        camera: onThreeCamera,
        select: id => {
          if (branchByAnchor.value.has(id) && !expandedBranches.value.has(id)) revealBranch(id)
          else selectNode(id)
        },
        failure: () => {
          handleRendererFailure()
        },
      })
      threeUnavailable.value = false
      await renderGraph3d()
    } catch {
      threeUnavailable.value = true
      handleRendererFailure()
    }
  })().finally(() => { threeInitializing = null })
  return threeInitializing
}

function handleRendererFailure(): void {
  threeUnavailable.value = true
  threeHasMap.value = false
  layoutPending.value = false
  chartReady.value = true
  threeRenderGeneration++
  cancelThreeLayout?.()
  threeLayout = null
  threeLayoutKey = []
  threeScene?.dispose()
  threeScene = null
}

async function retryRenderer(): Promise<void> {
  threeUnavailable.value = false
  await initializeRenderer()
}

async function renderGraph3d(fit = false, preserveView = false): Promise<void> {
  const instance = threeScene
  if (!instance) return
  const generation = ++threeRenderGeneration
  const key = [layoutSignature.value, hiddenEntityKinds.value]
  if (key.some((value, index) => value !== threeLayoutKey[index])) {
    const reorganize = key[1] !== threeLayoutKey[1]
    cancelThreeLayout?.()
    threeLayoutKey = key
    layoutPending.value = visibleNodes.value.length > 0
    const layout = hiddenEntityKinds.value.size ? filteredLayout : branchLayout
    threeLayout = new Promise<Graph3dLayoutResult | null>(resolve => {
      const worker = new Worker(new URL('../graph3d.worker.ts', import.meta.url), { type: 'module' })
      threeWorker = worker
      const finish = (result: Graph3dLayoutResult | null): void => {
        worker.terminate()
        if (threeWorker === worker) { threeWorker = null; cancelThreeLayout = null }
        resolve(result)
      }
      cancelThreeLayout = () => finish(null)
      worker.onmessage = (event: MessageEvent<Graph3dLayoutResult>) => finish(event.data)
      worker.onerror = () => {
        finish(null)
        if (threeScene === instance && !threeDisposed) {
          threeUnavailable.value = true
          handleRendererFailure()
        }
      }
      worker.postMessage({ generation, nodes: visibleNodes.value, edges: visibleEdges.value,
        branches: branches.value, positions: [...layout.positions],
        points: reorganize ? [] : [...threePoints] })
    })
  }
  let result: Graph3dLayoutResult | null
  try {
    result = await threeLayout
  } catch {
    if (generation !== threeRenderGeneration || threeDisposed) return
    layoutPending.value = false
    threeUnavailable.value = true
    handleRendererFailure()
    return
  }
  if (!result || generation !== threeRenderGeneration || threeScene !== instance) return
  const layout = hiddenEntityKinds.value.size ? filteredLayout : branchLayout
  for (const [id, point] of result.positions) layout.positions.set(id, point)
  threePoints = new Map(result.points)
  const members = new Map(branches.value.filter(branch => !expandedBranches.value.has(branch.anchorId))
    .map(branch => [branch.anchorId, branch.memberIds.length]))
  const palette = getComputedStyle(threeElement.value!)
  const markers = renderedNodes.value.flatMap(node => {
    const point = threePoints.get(node.id)
    if (!point) return []
    const grouped = members.get(node.id) ?? 0
    const paint = nodePaintStyle(node, false, palette)
    return [{ id: node.id, title: node.title, point, grouped, hiddenMass: hiddenItems.value.mass.get(node.id) ?? 0,
      ...paint, selectedBorderColor: nodePaintStyle(node, true, palette).borderColor,
      symbol: nodeSymbol(node), size: nodeBaseSymbolSize(node),
      shape: node.entity_kind === 'memory' ? 0 : node.entity_kind === 'topic' ? 1 : 2,
      priority: node.id === selectedNodeId.value ? 100 : grouped ? 30 : graphNodeLevel(node) === 0 ? 40
        : isStructuralNode(node) ? 10 : graphNodeLevel(node) === 1 ? 8 : 0 }]
  })
  instance.setTheme($q.dark.isActive ? solaire.gray.light : solaire.gray.dark)
  const edgeOpacityScale = Math.min(1, Math.sqrt(200 / Math.max(1, renderedEdges.value.length)))
  const curvatures = parallelEdgeCurvatures()
  instance.setData(markers, renderedEdges.value.map(edge => {
    const detail = edgePaintStyle(edge, false, edgeOpacityScale, palette)
    const overview = edgePaintStyle(edge, true, edgeOpacityScale, palette)
    return { source: edge.source_item_id, target: edge.target_item_id, ...detail, type: edge.relation_type,
      width: detail.width * 1.25, curvature: curvatures.get(edge.id) ?? 0.22,
      overviewStyle: { width: overview.width * 2.25, opacity: overview.opacity }, suggested: edge.suggested }
  }),
  markers.map(marker => marker.point), fit || !threeHasMap.value, {
    nodes: [...nodes.value.values()], edges: [...edges.value.values()], representatives: hiddenRepresentatives.value,
  }, preserveView)
  if (!threeHasMap.value && threeCamera && !fit) instance.restore(threeCamera)
  threeHasMap.value = markers.length > 0
  instance.setSelected(selectedNodeId.value)
  layoutPending.value = false
  chartReady.value = true
  if (!hiddenEntityKinds.value.size) {
    stagePositions()
    scheduleViewSave()
  }
  scheduleThumbnails()
}

function onThreeCamera(): void {
  const instance = threeScene
  if (!instance || !threeHasMap.value) return
  spatialGroupedCount.value = instance.groupedCount
  spatialHiddenCount.value = instance.hiddenCount
  const next = instance.zoom <= BRANCH_CLOSE_ZOOM ? new Set<string>() : new Set(expandedBranches.value)
  if (instance.zoom >= BRANCH_OPEN_ZOOM) for (const branch of branches.value) {
    if (instance.visible.has(branch.anchorId) && instance.spacingAt(branch.anchorId, 56) >= 40) next.add(branch.anchorId)
  }
  const changed = next.size !== expandedBranches.value.size || [...next].some(id => !expandedBranches.value.has(id))
  if (changed) {
    expandedBranches.value = next
    void renderGraph3d()
  }
  scheduleThumbnails()
  stagePresentation()
  const canLoad = !loading.value && !reloading.value && !error.value && instance.zoom >= BRANCH_OPEN_ZOOM
  const candidates = canLoad ? [...instance.visible.values()].filter(point => point.near
      && directoriesWithUnloadedChildren.value.has(point.id))
      .sort((a, b) => b.depth - a.depth) : []
  threeChildren?.update(candidates.map(point => point.id), JSON.stringify(instance.view))
}

function updateThreeThumbnails(): void {
  const instance = threeScene
  if (!instance || agentId === null) return
  const candidates: (GraphThumbnailCandidate & { distance: number })[] = []
  for (const [id, point] of instance.visible) {
    const node = nodes.value.get(id)
    if (!point.near || !node || isAudioNode(node)
      || (node.node_kind !== 'file' && node.node_kind !== 'attachment' && node.node_kind !== 'document')) continue
    if (point.x < 0 || point.x > viewportSize.width || point.y < 0 || point.y > viewportSize.height) continue
    const key = thumbnailKey(node)
    if (thumbnails.unavailable(key)) continue
    candidates.push({ node, key, distance: selectedNodeId.value === id ? -1
      : Math.hypot(point.x - viewportSize.width / 2, point.y - viewportSize.height / 2) })
  }
  thumbnailKeys.clear()
  const wanted = candidates.sort((a, b) => a.distance - b.distance).slice(0, thumbnailBudget)
  for (const candidate of wanted) thumbnailKeys.set(candidate.node.id, candidate.key)
  thumbnails.update(wanted)
  paintThreeThumbnails()
}

function paintThreeThumbnails(): void {
  // Resource metadata may resolve after placement; replace its glyph without
  // changing positions, the camera, node sizes or the thumbnail lifecycle.
  threeScene?.setSymbols(new Map(renderedNodes.value.map(node => [node.id, nodeSymbol(node)])))
  const previews = new Map<string, Graph3dPreview>()
  for (const [id, key] of thumbnailKeys) {
    const url = thumbnails.url(key)
    if (url) previews.set(id, { url, aspect: thumbnails.aspect(key), nativeSize: thumbnails.longestSide(key) })
  }
  threeScene?.setPreviews(previews)
}

function setFullscreen(value: boolean): void {
  if (isFullscreen.value === value) return
  isFullscreen.value = value
  if (value) {
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  } else if (previousBodyOverflow !== null) {
    document.body.style.overflow = previousBodyOverflow
    previousBodyOverflow = null
  }
  void nextTick().then(resizeChart)
}

async function enterFullscreen(): Promise<void> {
  if (document.fullscreenEnabled && document.fullscreenElement === null) {
    try {
      await document.documentElement.requestFullscreen({ navigationUI: 'hide' })
    } catch {
      // Keep the viewport-sized fallback when native fullscreen is unavailable or denied.
    }
  }
  setFullscreen(true)
}

async function exitFullscreen(): Promise<void> {
  if (document.fullscreenElement !== null) {
    try {
      await document.exitFullscreen()
    } catch {
      // The CSS fullscreen state can still be closed independently.
    }
  }
  setFullscreen(false)
}

function toggleFullscreen(): void {
  void (isFullscreen.value ? exitFullscreen() : enterFullscreen())
}

function onFullscreenChange(): void {
  if (document.fullscreenElement === null && isFullscreen.value) {
    setFullscreen(false)
  }
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && isFullscreen.value && document.fullscreenElement === null) {
    setFullscreen(false)
  }
}

watch(
  [
    () => agentId,
    () => query,
    () => topicItemId,
    () => contactItemId,
  ],
  () => {
    void loadInitial()
  },
  { immediate: true },
)

watch(
  () => $q.dark.isActive,
  () => renderGraph(),
)

onMounted(() => {
  websocket.createWebsocket()
  websocket.onEvent('memory', 'invalidate', invalidateAccess)
  websocket.onConnect(onGraphReconnect)
  void initializeRenderer()
  resizeObserver = new ResizeObserver(resizeChart)
  if (viewport.value) resizeObserver.observe(viewport.value)
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, onGraphSessionChange)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  registerInterval(() => {
    void refreshLatestRoots()
  }, AUTO_REFRESH_INTERVAL)
})

onUnmounted(() => {
  stagePresentation()
  void persistence?.flush()
  persistence = null
  threeDisposed = true
  threeChildren?.dispose()
  threeRenderGeneration++
  cancelThreeLayout?.()
  threeWorker?.terminate()
  threeScene?.dispose()
  threeScene = null
  removeSaveTimeout()
  unsubscribeThumbnailReady()
  thumbnails.clear()
  thumbnailResources.clear()
  if (thumbnailPaintTimer !== null) clearTimeout(thumbnailPaintTimer)
  if (thumbnailFrame !== null) cancelAnimationFrame(thumbnailFrame)
  websocket.offEvent('memory', 'invalidate', invalidateAccess)
  websocket.offConnect(onGraphReconnect)
  loadGeneration += 1
  rootController?.abort()
  resizeObserver?.disconnect()
  removeInterval()
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, onGraphSessionChange)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  if (isFullscreen.value && document.fullscreenElement !== null) {
    void document.exitFullscreen().catch(() => undefined)
  }
  if (previousBodyOverflow !== null) {
    document.body.style.overflow = previousBodyOverflow
    previousBodyOverflow = null
  }
})
</script>

<style scoped>
.memory-graph {
  overflow: hidden;
}

.memory-graph__header {
  padding: 0 12px 8px;
}

.memory-graph--fullscreen {
  position: fixed;
  z-index: 5999;
  inset: 0;
  display: flex;
  width: 100vw;
  height: 100vh;
  height: 100dvh;
  flex-direction: column;
  border: 0;
  border-radius: 0;
}

.memory-graph--fullscreen .memory-graph__layout {
  min-height: 0;
  flex: 1 1 auto;
  aspect-ratio: auto;
}

.memory-graph--fullscreen .memory-graph__viewport {
  min-height: 0;
}

.memory-graph__layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-height: 0;
  aspect-ratio: 1.61803398875 / 1;
}

.memory-graph__refresh-controls {
  min-height: 34px;
  padding: 2px 3px 2px 2px;
  border: 1px solid rgba(25, 118, 210, 0.28);
  border-radius: 999px;
  background: rgba(25, 118, 210, 0.06);
}

.memory-graph__legend-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 10px;
  background: #fff;
  color: #455a64;
  font-size: 11px;
}

.memory-graph__legend-group {
  flex: 1 1 260px;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid rgba(69, 90, 100, 0.13);
  border-radius: 8px;
  background: rgba(96, 125, 139, 0.035);
}

.memory-graph__legend-group--view {
  display: flex;
  flex-basis: 280px;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.memory-graph__legend-group--links {
  font-size: 12px;
}

.memory-graph__fullscreen-control {
  box-shadow: 0 2px 8px rgba(25, 118, 210, 0.38);
}

.memory-graph__fullscreen-control--active {
  box-shadow: 0 0 0 3px rgba(25, 118, 210, 0.2), 0 3px 10px rgba(25, 118, 210, 0.42);
}

.memory-graph__legend-title {
  margin-bottom: 3px;
  font-weight: 600;
}

.memory-graph__legend-items {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 1px 3px;
}

.memory-graph__legend-items--links {
  gap: 4px 10px;
}

.memory-graph__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.memory-graph__freshness-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #607d8b;
  font-size: 12px;
}

.memory-graph__type-filter {
  min-height: 22px;
  padding: 0 4px;
  border-radius: 6px;
}

.memory-graph__type-filter :deep(.q-btn__content) {
  gap: 4px;
}

.memory-graph__type-filter--hidden {
  opacity: 0.5;
  text-decoration: line-through;
}

.memory-graph__type-legend-dot {
  width: 10px;
  height: 10px;
  flex: 0 0 auto;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(38, 50, 56, 0.14);
}

.memory-graph__role-symbol {
  width: 11px;
  height: 11px;
  flex: 0 0 auto;
  border: 1px solid rgba(255, 255, 255, 0.72);
  box-shadow: 0 0 0 1px rgba(38, 50, 56, 0.2);
}

.memory-graph__role-symbol--topic {
  border-radius: 2px;
  transform: rotate(45deg);
}

.memory-graph__role-symbol--contact {
  width: 14px;
  border-radius: 4px;
}

.memory-graph__role-symbol--document {
  border-radius: 1px;
}

.memory-graph__role-symbol--conversation {
  width: 14px;
  border-radius: 6px;
}

.memory-graph__link-legend-line {
  width: 20px;
  height: 0;
  flex: 0 0 auto;
  border-top: 2px solid #607d8b;
}

.memory-graph__link-legend-line--suggested {
  border-top-style: dashed;
}

.memory-graph__viewport {
  position: relative;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at 25% 20%, rgba(33, 150, 243, 0.08), transparent 34%),
    radial-gradient(circle at 78% 72%, rgba(126, 87, 194, 0.08), transparent 36%),
    linear-gradient(rgba(69, 90, 100, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(69, 90, 100, 0.055) 1px, transparent 1px),
    #fafbfd;
  background-size: auto, auto, 32px 32px, 32px 32px, auto;
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.memory-graph__viewport:active {
  cursor: grabbing;
}

.memory-graph__chart--3d {
  display: block;
  width: 100%;
  height: 100%;
  outline: none;
  transition: opacity 120ms ease-out;
}

.memory-graph__chart--loading {
  opacity: 0;
}

.memory-graph__chart--3d {
  position: relative;
}

.memory-graph__navigation-hint {
  position: absolute;
  bottom: 8px;
  left: 12px;
  right: 12px;
  pointer-events: none;
  font-size: 11px;
  color: var(--solaire-gray-accent);
}

.memory-graph__chart--3d:focus-visible {
  box-shadow: inset 0 0 0 3px var(--q-primary);
}

.memory-graph__freshness-endpoint {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.memory-graph__freshness-endpoint time {
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.memory-graph__freshness-samples {
  display: flex;
  align-items: center;
  gap: 6px;
}

.memory-graph__freshness-sample {
  flex-shrink: 0;
  border-radius: 50%;
}

.memory-graph__empty {
  position: absolute;
  top: 50%;
  left: 50%;
  text-align: center;
  transform: translate(-50%, -50%);
}

.memory-graph__detail {
  width: min(640px, 96vw);
  max-height: 90vh;
}

.memory-graph--dark {
  border-color: rgba(255, 255, 255, 0.1);
  background: #1d2027;
  color: #e5e9f0;
}

.memory-graph--dark .memory-graph__header,
.memory-graph--dark .memory-graph__legend-panel {
  background: #20242c;
}

.memory-graph--dark .memory-graph__refresh-controls {
  border-color: rgba(144, 202, 249, 0.3);
  background: rgba(144, 202, 249, 0.08);
}

.memory-graph--dark .memory-graph__legend-panel {
  color: #c9d1df;
}

.memory-graph--dark .memory-graph__legend-group {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.025);
}

.memory-graph--dark .memory-graph__freshness-legend {
  color: #c9d1df;
}

.memory-graph--dark .memory-graph__type-legend-dot {
  border-color: rgba(255, 255, 255, 0.26);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.34);
}

.memory-graph--dark .memory-graph__role-symbol {
  border-color: rgba(255, 255, 255, 0.26);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.34);
}

.memory-graph--dark .memory-graph__banner--neutral {
  color: #c5ccd8;
}

.memory-graph--dark .memory-graph__banner--negative {
  color: #ef9a9a !important;
}

.memory-graph--dark .memory-graph__banner--warning {
  color: #ffcc80 !important;
}

.memory-graph--dark .memory-graph__banner--info {
  color: #90caf9 !important;
}

.memory-graph--dark .memory-graph__viewport {
  background:
    radial-gradient(circle at 25% 20%, rgba(66, 165, 245, 0.15), transparent 34%),
    radial-gradient(circle at 78% 72%, rgba(179, 157, 219, 0.14), transparent 36%),
    linear-gradient(rgba(255, 255, 255, 0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.025) 1px, transparent 1px),
    #14171d;
  background-size: auto, auto, 32px 32px, 32px 32px, auto;
}

@media (min-width: 1440px) {
  .memory-graph__legend-panel {
    display: grid;
    grid-template-columns: minmax(0, 38fr) minmax(0, 38fr) minmax(0, 24fr);
  }
}

@media (max-width: 1023px) {
  .memory-graph--fullscreen .memory-graph__header,
  .memory-graph--fullscreen .memory-graph__header-separator,
  .memory-graph--fullscreen .memory-graph__legend-separator {
    display: none;
  }

  .memory-graph--fullscreen .memory-graph__legend-panel {
    position: absolute;
    z-index: 3;
    top: max(8px, env(safe-area-inset-top));
    right: max(8px, env(safe-area-inset-right));
    display: block;
    padding: 0;
    background: transparent;
  }

  .memory-graph--fullscreen .memory-graph__legend-group {
    display: none;
  }

  .memory-graph--fullscreen .memory-graph__legend-group--view {
    display: block;
    padding: 0;
    border: 0;
    background: transparent;
  }

  .memory-graph--fullscreen .memory-graph__freshness-legend {
    display: none;
  }

  .memory-graph--fullscreen .memory-graph__view-controls {
    padding: 4px;
    background: rgba(255, 255, 255, 0.9);
    box-shadow: 0 4px 16px rgba(38, 50, 56, 0.18);
    backdrop-filter: blur(8px);
  }

  .memory-graph--fullscreen.memory-graph--dark .memory-graph__view-controls {
    background: rgba(32, 36, 44, 0.9);
  }
}

@media (max-width: 699px) {
  .memory-graph__header-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .memory-graph__legend-panel {
    padding: 7px;
  }
}

@media (max-width: 420px) {
  .memory-graph__header-actions {
    justify-content: flex-start;
  }

  .memory-graph__refresh-controls {
    order: 1;
    width: 100%;
    justify-content: space-between;
  }
}
</style>
