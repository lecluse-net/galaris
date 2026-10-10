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
        <q-btn-group outline>
          <q-btn :color="viewMode === '3d' ? 'primary' : undefined" :label="t('memory.graph.view3d')" :aria-pressed="viewMode === '3d'" @click="changeViewMode('3d')" />
          <q-btn :color="viewMode === '2d' ? 'primary' : undefined" :label="t('memory.graph.view2d')" :aria-pressed="viewMode === '2d'" @click="changeViewMode('2d')" />
        </q-btn-group>
        <q-chip dense outline icon="hub">
          {{ t('memory.graph.nodeCount', { count: visibleNodes.length }) }}
        </q-chip>
        <q-chip dense outline icon="timeline">
          {{ t('memory.graph.edgeCount', { count: visibleEdges.length }) }}
        </q-chip>
        <q-chip v-if="groupedNodeCount" dense outline icon="account_tree" role="status">
          {{ t('memory.graph.groupedCount', { count: groupedNodeCount }) }}
        </q-chip>
        <div class="memory-graph__refresh-controls row items-center no-wrap">
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
        <div class="memory-graph__view-controls row items-center q-gutter-xs no-wrap">
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
        </div>
      </section>
    </div>

    <q-separator v-if="agentId !== null" class="memory-graph__legend-separator" />

    <div v-if="agentId !== null" class="memory-graph__layout">
      <div
        ref="viewport"
        class="memory-graph__viewport"
      >
        <div
          v-show="viewMode === '2d'"
          ref="chartElement"
          class="memory-graph__chart"
          :class="{ 'memory-graph__chart--loading': graphBusy }"
          role="img"
          tabindex="0"
          :aria-label="t('memory.graph.canvasLabel')"
        />
        <div
          v-show="viewMode === '3d'"
          ref="threeElement"
          class="memory-graph__chart--3d"
          :class="{ 'memory-graph__chart--loading': graphBusy }"
          role="application"
          tabindex="0"
          :aria-label="t('memory.graph.canvas3dLabel')"
          :aria-description="t('memory.graph.navigation3d')"
        />
        <div v-if="viewMode === '3d' && !graphBusy" class="memory-graph__navigation-hint">
          {{ t('memory.graph.navigation3d') }}
        </div>

        <div v-if="!graphBusy && visibleNodes.length === 0" class="memory-graph__empty">
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
import { websocket } from '@/core/websocket'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration, SupersededSessionError } from '@/core/api'
import { browserResourceKind, solaire, solaireCss, type BrowserResourceKind, type SolaireColor } from '@/core/util'
import { useInterval, useQuasar, useTimeout } from 'quasar'
import { matAudioFile, matDescription, matImage, matVideoFile } from '@quasar/extras/material-icons'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { AriaComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { LabelLayout } from 'echarts/features'
import type { ECElementEvent, ECharts, EChartsCoreOption, ElementEvent } from 'echarts/core'
import type { GraphSeriesOption } from 'echarts/charts'
import MemoryGraphNodeDetail from './MemoryGraphNodeDetail.vue'
import { memoryService } from '../services/memoryService'
import { graphBranches, GraphBranchLayout, BRANCH_OPEN_ZOOM, BRANCH_CLOSE_ZOOM } from '../graphBranches'
import { GraphThumbnails, type GraphThumbnailCandidate } from '../graphThumbnails'
import { onThumbnailReady } from '../thumbnailEvents'
import { graphViewportData } from '../graphViewport'
import { GraphStatePersistence, type GraphPreferences, type GraphContext } from '../graphState'
import type { MemoryGraphScene, Graph3dCamera, Graph3dPreview } from '../graph3dScene'
import type { Graph3dLayoutResult, GraphPoint3d } from '../graph3dLayout'
import type {
  CatalogueResource,
  MemoryGraphCursor,
  MemoryGraphEdge,
  MemoryGraphEntityKind,
  MemoryGraphNode,
  MemoryGraphPage,
  MemoryGraphRelation,
} from '../types'

interface ScreenPoint {
  x: number
  y: number
}

interface GraphViewState {
  center: GraphSeriesOption['center']
  zoom: GraphSeriesOption['zoom']
}

type MemoryGraphOption = EChartsCoreOption & {
  series: GraphSeriesOption[]
}

echarts.use([GraphChart, AriaComponent, CanvasRenderer, LabelLayout])

const {
  agentId,
  query,
  topicItemId,
  contactItemId,
  renderer = '2d',
} = defineProps<{
  agentId: number | null
  query: string
  topicItemId: string | null
  contactItemId: string | null
  renderer?: '2d' | '3d'
}>()

const emit = defineEmits<{
  open: [id: string, node: MemoryGraphNode, relations: MemoryGraphRelation[]]
}>()

const ROOT_PAGE_SIZE = 500
const AUTO_REFRESH_INTERVAL = 30_000
const MIN_ZOOM = 1
const MAX_ZOOM = 1_000_000
const MOBILE_GRAPH_MEDIA_QUERY = '(max-width: 1023px)'
const MOBILE_PINCH_ZOOM_SENSITIVITY = 0.35
const MOBILE_DETAIL_OPEN_DELAY = 50
const GRAPH_SERIES_ID = 'memory-graph'
const LINK_WIDTH_SCALE = 0.8
const LAYOUT_REBALANCE_MILLISECONDS = 700
const REVEAL_DURATION_MILLISECONDS = 320
const REVEAL_SPREAD_MILLISECONDS = 120
const MAX_ANIMATED_VISIBLE_NODES = 500
const NODE_MIN_RADIUS = 10
const NODE_RADIUS_RANGE = 8
const NODE_SCALE_RATIO = 0.000001
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
const { registerTimeout: registerMobileDetailTimeout, removeTimeout: removeMobileDetailTimeout } = useTimeout()
const { registerTimeout: registerLayoutTimeout, removeTimeout: removeLayoutTimeout } = useTimeout()
const { registerTimeout: registerThumbnailTimeout, removeTimeout: removeThumbnailTimeout } = useTimeout()
const { registerTimeout: registerSaveTimeout, removeTimeout: removeSaveTimeout } = useTimeout()
const { registerInterval: registerPositionInterval, removeInterval: removePositionInterval } = useInterval()
const viewport = useTemplateRef<HTMLDivElement>('viewport')
const chartElement = useTemplateRef<HTMLDivElement>('chartElement')
const threeElement = useTemplateRef<HTMLDivElement>('threeElement')
const viewMode = ref<'2d' | '3d'>(renderer)
const spatialGroupedCount = ref(0)
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
let threeHasMap = false
const nodes = shallowRef(new Map<string, MemoryGraphNode>())
const edges = shallowRef(new Map<string, MemoryGraphEdge>())
const expandedBranches = shallowRef(new Set<string>())
const branchLayout = new GraphBranchLayout()
const filteredLayout = new GraphBranchLayout()
// Keep the original animated physics for ordinary graphs; larger windows use the bounded layout.
const dynamicLayout = computed(() => nodes.value.size <= 600)
const overview = ref(false)
const allTitles = ref(false)
let symbolZoom = 1
const previewClearance = new Map<string, number>()
const hiddenEntityKinds = shallowRef(new Set<MemoryGraphEntityKind>())
const hasStoredLayout = ref(false)
const viewStateError = ref<unknown>(null)
let persistence: GraphStatePersistence | null = null
let restoredCamera: GraphViewState | null = null
let previousPositionSample = new Map<string, ScreenPoint>()
let stablePositionSamples = 0
let graphSession = sessionGeneration()
const selectedNodeId = ref<string | null>(null)
const edgesTruncated = ref(false)
const loading = ref(false)
const reloading = ref(false)
const refreshing = ref(false)
const liveRefresh = ref(true)
const error = ref<unknown>(null)
const isFullscreen = ref(false)
const layoutPending = ref(false)
const chartReady = ref(false)
const viewportSize = reactive({ width: 0, height: 0 })

let resizeObserver: ResizeObserver | null = null
let chart: ECharts | null = null
let previousBodyOverflow: string | null = null
let loadGeneration = 0
let rootController: AbortController | null = null
let layoutGeneration = 0
let renderFrame: number | null = null
let hasLayoutStarted = false
let layoutRelaxationEnabled = false
let lastRenderedIds = new Set<string>()
let thumbnailsNear = false
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
const collapsedMemberIds = computed(() => new Set(branches.value
  .filter(branch => !expandedBranches.value.has(branch.anchorId))
  .flatMap(branch => branch.memberIds.filter(id => id !== selectedNodeId.value))))
const groupedNodeCount = computed(() => collapsedMemberIds.value.size + (viewMode.value === '3d' ? spatialGroupedCount.value : 0))
const renderedNodes = computed(() => visibleNodes.value.filter(node => !collapsedMemberIds.value.has(node.id)))
const nodeShadowStyle = computed(() => ({
  shadowColor: echarts.color.modifyAlpha(solaire.gray.accent, 0.28),
  shadowBlur: overview.value || renderedNodes.value.length > 500 ? 0 : 5,
  shadowOffsetX: 0,
  shadowOffsetY: 2,
}))
const renderedEdges = computed(() => visibleEdges.value.filter(edge => (
  !collapsedMemberIds.value.has(edge.source_item_id) && !collapsedMemberIds.value.has(edge.target_item_id)
)))
const selectedNode = computed(() => {
  if (selectedNodeId.value === null) return null
  const node = nodes.value.get(selectedNodeId.value)
  return node && isNodeVisible(node) ? node : null
})

const graphBusy = computed(() => loading.value || layoutPending.value || !chartReady.value)
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
  if (viewMode.value === '3d') {
    expandedBranches.value = new Set()
    void renderGraph3d(true)
    return
  }
  renderGraph({
    viewState: { center: ['50%', '50%'], zoom: 1 },
    preserveSelection: true,
    relax: false,
  })
}


function toggleEntityKind(kind: MemoryGraphEntityKind): void {
  freezePositions()
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

function nodeThumbnailUrl(node: MemoryGraphNode): string | null {
  const key = thumbnailKeys.get(node.id)
  return key ? thumbnails.url(key) : null
}

function nodeSymbol(node: MemoryGraphNode, withThumbnail = true): string {
  const resourceKind = nodeResourceKind(node)
  if (resourceKind === 'audio') return mediaFileSymbols.audio
  const url = withThumbnail ? nodeThumbnailUrl(node) : null
  if (url) return `image://${url}`
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

function nodeBaseSymbolSize(node: MemoryGraphNode, groupedCount = 0): number {
  const scale = dynamicLayout.value ? Math.min(1, Math.max(0.35, Math.min(viewportSize.width, viewportSize.height) / 650)) : 1
  const size = (radiusFor(node) * 2 + Math.min(44, Math.log2(groupedCount + 1) * 5)) * scale
  return size
}

function nodeSymbolSize(node: MemoryGraphNode, groupedCount = 0): number | [number, number] {
  // Exactly two screen sizes: distant and near. Further zoom only spreads the
  // coordinates. Compensate even ECharts' tiny residual scale (zero means one).
  const near = symbolZoom >= BRANCH_OPEN_ZOOM
  const compensation = 1 / (1 + (symbolZoom - 1) * NODE_SCALE_RATIO)
  const size = Math.min(groupedCount ? 56 : 48, nodeBaseSymbolSize(node, groupedCount)) * (near ? 1.1 : 0.56)
  if (!nodeThumbnailUrl(node)) return (isAudioNode(node) && near ? Math.max(22, size) : size) * compensation
  const key = thumbnailKeys.get(node.id)
  const aspect = key ? thumbnails.aspect(key) : 1
  const nativeSize = key ? thumbnails.longestSide(key) : 320
  const distantSize = size * 1.75
  // Delay preview growth until zoom 3, then follow the camera up to one
  // decoded image pixel per CSS pixel. Neighbor clearance can delay it further.
  const desired = near ? Math.min(112, Math.max(40, size * 1.75)) * Math.max(1, symbolZoom / 3) : distantSize
  const longest = Math.min(nativeSize, desired, previewClearance.get(node.id) ?? nativeSize) * compensation
  // ECharts fits images inside a unit square before scaling to symbolSize.
  // These dimensions already preserve the ratio, so image symbols must disable that fitting.
  return aspect >= 1 ? [longest, longest / aspect] : [longest * aspect, longest]
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

function revealBranch(id: string, anchor?: ScreenPoint): void {
  freezePositions()
  expandedBranches.value = new Set([...expandedBranches.value, id])
  persistence?.stagePreferences({ expanded_branches: [...expandedBranches.value] })
  scheduleViewSave()
  if (viewMode.value === '3d') {
    void renderGraph3d().then(() => threeScene?.focus(id))
    return
  }
  const clicked: unknown = dynamicLayout.value && anchor
    ? chart?.convertFromPixel({ seriesId: GRAPH_SERIES_ID }, [anchor.x, anchor.y]) : null
  const point = Array.isArray(clicked) && typeof clicked[0] === 'number' && typeof clicked[1] === 'number'
    ? { x: clicked[0], y: clicked[1] } : (hiddenEntityKinds.value.size ? filteredLayout : branchLayout).positions.get(id)
  const view = captureGraphView()
  let zoom = Math.max(BRANCH_OPEN_ZOOM, view?.zoom ?? 1)
  if (!dynamicLayout.value && point && chart) {
    const center: unknown = chart.convertToPixel({ seriesId: GRAPH_SERIES_ID }, [point.x, point.y])
    const nearby: unknown = chart.convertToPixel({ seriesId: GRAPH_SERIES_ID }, [point.x + 56, point.y])
    if (Array.isArray(center) && Array.isArray(nearby)) {
      zoom = Math.min(MAX_ZOOM, Math.max(zoom, (view?.zoom ?? 1) * 48 / Math.max(1, Math.abs(nearby[0] - center[0]))))
    }
  }
  renderGraph({
    viewState: { center: point ? [point.x, point.y] : view?.center, zoom },
    preserveSelection: true,
    relax: false,
  })
  stagePresentation()
}

function onGraphRoam(): void {
  freezePositions()
  closeInspector(false)
  const view = captureGraphView()
  const zoom = view?.zoom ?? 1
  if (zoom <= MIN_ZOOM + 0.000001) {
    fitGraph()
    scheduleThumbnails()
    return
  }
  allTitles.value = zoom >= BRANCH_OPEN_ZOOM
  if (zoom <= 1.2) overview.value = true
  else if (zoom >= 1.5) overview.value = false
  let next: Set<string> | null = null
  if (zoom <= BRANCH_CLOSE_ZOOM && expandedBranches.value.size) next = new Set()
  else if (zoom >= BRANCH_OPEN_ZOOM) {
    next = new Set(expandedBranches.value)
    for (const branch of branches.value) {
      // Small windows reveal their pre-positioned branches together; larger
      // static windows reveal only viewport anchors.
      if (dynamicLayout.value) { next.add(branch.anchorId); continue }
      const point = (hiddenEntityKinds.value.size ? filteredLayout : branchLayout).positions.get(branch.anchorId)
      if (!point || !chart) continue
      if (branch.memberIds.length >= 8) {
        const center: unknown = chart.convertToPixel({ seriesId: GRAPH_SERIES_ID }, [point.x, point.y])
        const nearby: unknown = chart.convertToPixel({ seriesId: GRAPH_SERIES_ID }, [point.x + 56, point.y])
        if (!Array.isArray(center) || !Array.isArray(nearby) || Math.abs(nearby[0] - center[0]) < 40) continue
      }
      const screen: unknown = chart.convertToPixel({ seriesId: GRAPH_SERIES_ID }, [point.x, point.y])
      if (Array.isArray(screen) && typeof screen[0] === 'number' && typeof screen[1] === 'number'
        && screen[0] >= 0 && screen[0] <= viewportSize.width && screen[1] >= 0 && screen[1] <= viewportSize.height) {
        next.add(branch.anchorId)
      }
    }
  }
  const branchesChanged = next && (next.size !== expandedBranches.value.size || [...next].some(id => !expandedBranches.value.has(id)))
  if (branchesChanged && next) {
    expandedBranches.value = next
  }
  // Refresh screen sizes, visible labels and the large-map window on every
  // camera change, including panning after a branch has already been opened.
  renderGraph({ viewState: view, preserveSelection: true, relax: false })
  scheduleThumbnails()
  stagePresentation()
}

function thumbnailKey(node: MemoryGraphNode): string {
  return `${agentId}:${node.id}:${node.updated_at ?? node.activity_at}:${node.resource_uri ?? ''}`
}

function scheduleThumbnails(): void {
  registerThumbnailTimeout(updateThumbnails, 120)
}

function updateThumbnails(): void {
  if (viewMode.value === '3d') {
    updateThreeThumbnails()
    return
  }
  const instance = chart
  if (!instance || agentId === null) return
  const zoom = captureGraphView()?.zoom ?? 1
  if (zoom >= 1.8) thumbnailsNear = true
  else if (zoom <= 1.5) thumbnailsNear = false
  const candidates: (GraphThumbnailCandidate & { distance: number })[] = []
  if (thumbnailsNear && !overview.value) {
    // Read the typed data model only; never mutate positions or renderer internals.
    const data = graphViewportData(instance)
    if (data) for (let index = 0; index < data.count(); index++) {
      const id = data.getId(index)
      const node = nodes.value.get(id)
      if (!node || !visibleNodeIds.value.has(id) || collapsedMemberIds.value.has(id)
        || isAudioNode(node)
        || (node.node_kind !== 'file' && node.node_kind !== 'attachment' && node.node_kind !== 'document')) continue
      const position: unknown = data.getItemLayout(index)
      if (!Array.isArray(position)) continue
      const screen: unknown = instance.convertToPixel({ seriesId: GRAPH_SERIES_ID }, position)
      if (!Array.isArray(screen) || typeof screen[0] !== 'number' || typeof screen[1] !== 'number') continue
      const key = thumbnailKey(node)
      const retained = thumbnailKeys.get(id) === key
      const loaded = retained && thumbnails.url(key) !== null
      const inViewport = screen[0] >= 0 && screen[0] <= viewportSize.width
        && screen[1] >= 0 && screen[1] <= viewportSize.height
      // Keep loaded images outside the viewport until the display budget is full.
      // Only pending reads use a small margin; new reads start inside the viewport.
      const margin = retained ? 100 : 0
      if (!loaded && (screen[0] < -margin || screen[0] > viewportSize.width + margin
        || screen[1] < -margin || screen[1] > viewportSize.height + margin)) continue
      // Near-view thumbnails have their own readable minimum size. An old/small
      // role square must not prevent the file from receiving its larger preview.
      candidates.push({ node, key, distance: selectedNodeId.value === id ? -1
        : (inViewport ? 0 : Math.hypot(viewportSize.width, viewportSize.height))
          + Math.hypot(screen[0] - viewportSize.width / 2, screen[1] - viewportSize.height / 2) - (retained ? 80 : 0) })
    }
  }
  const previousKeys = new Map(thumbnailKeys)
  thumbnailKeys.clear()
  // Missing derivatives do not occupy display slots. Bound the search for
  // replacements as well, rather than scanning every file in a dense window.
  const wanted = candidates.sort((a, b) => a.distance - b.distance)
    .slice(0, thumbnailBudget * 2)
    .filter(candidate => !thumbnails.unavailable(candidate.key))
    .slice(0, thumbnailBudget)
  for (const candidate of wanted) thumbnailKeys.set(candidate.node.id, candidate.key)
  thumbnails.update(wanted)
  if (previousKeys.size !== thumbnailKeys.size || [...thumbnailKeys].some(([id, key]) => previousKeys.get(id) !== key)) {
    renderGraph({ viewState: captureGraphView(), preserveSelection: true, relax: false })
  }
  scheduleThumbnailPaint()
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
  if (viewMode.value === '3d') { paintThreeThumbnails(); return }
  const instance = chart
  if (!instance) return
  const option = instance.getOption() as unknown as MemoryGraphOption
  const series = option.series.find(series => series.id === GRAPH_SERIES_ID)
  if (!series?.data) return
  let changed = false
  const data = series.data.map(entry => {
    if (typeof entry !== 'object' || entry === null || !('id' in entry) || !('symbol' in entry)
      || entry.symbol === 'none') return entry
    const node = nodes.value.get(String(entry.id))
    if (!node) return entry
    const symbol = nodeSymbol(node)
    if (symbol === entry.symbol) return entry
    changed = true
    const style = 'itemStyle' in entry && typeof entry.itemStyle === 'object' && entry.itemStyle !== null
      ? entry.itemStyle : {}
    return { ...entry, symbol, symbolKeepAspect: !nodeThumbnailUrl(node), symbolSize: nodeSymbolSize(node),
      itemStyle: { ...style, ...nodeShadowStyle.value } }
  })
  if (changed) {
    // A symbol replacement preserves the camera, selection and native force cache.
    stopGraphLayout()
    instance.setOption({ series: [{ id: GRAPH_SERIES_ID, animation: false, data }] })
  }
}

function mergeNodes(incoming: MemoryGraphNode[]): string[] {
  const next = new Map(nodes.value)
  const addedIds: string[] = []
  for (const node of incoming) {
    const existing = next.get(node.id)
    if (existing) {
      next.set(node.id, { ...existing, ...node })
      continue
    }
    next.set(node.id, node)
    addedIds.push(node.id)
  }
  nodes.value = next
  return addedIds
}

function mergeEdges(incoming: MemoryGraphEdge[]): void {
  const next = new Map(edges.value)
  for (const edge of incoming) {
    if (!nodes.value.has(edge.source_item_id) || !nodes.value.has(edge.target_item_id)) continue
    next.set(edge.id, edge)
  }
  edges.value = next
}

function mergeRootPage(page: MemoryGraphPage): void {
  if (page.positions) {
    for (const [key, point] of Object.entries(page.positions)) {
      branchLayout.positions.set(key, { x: point[0], y: point[1] })
      hasStoredLayout.value = true
    }
    persistence?.remember(Object.entries(page.positions).map(([key, point]) => [key, { x: point[0], y: point[1] }]))
  }
  mergeNodes(page.nodes)
  mergeEdges(page.edges)
  edgesTruncated.value = edgesTruncated.value || page.edges_truncated
}

function graphPageHasChanges(page: MemoryGraphPage): boolean {
  for (const node of page.nodes) {
    const existing = nodes.value.get(node.id)
    if (!existing || JSON.stringify(existing) !== JSON.stringify(node)) return true
  }
  for (const edge of page.edges) {
    const existing = edges.value.get(edge.id)
    if (!existing || JSON.stringify(existing) !== JSON.stringify(edge)) return true
  }
  return false
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

function nodeLabel(node: MemoryGraphNode): string {
  if (isRootDirectory(node) && node.title === node.resource_uri) return node.title
  return node.title.length > 28 ? `${node.title.slice(0, 27)}…` : node.title
}

function isRootDirectory(node: MemoryGraphNode): boolean {
  return node.entity_kind === 'directory' && /^[a-z][a-z0-9+.-]*:\/\/\/?$/i.test(node.resource_uri ?? '')
}

function graphDegrees(): Map<string, number> {
  const degrees = new Map(visibleNodes.value.map(node => [node.id, 0]))
  for (const edge of visibleEdges.value) {
    if (edge.suggested) continue
    degrees.set(edge.source_item_id, (degrees.get(edge.source_item_id) ?? 0) + 1)
    degrees.set(edge.target_item_id, (degrees.get(edge.target_item_id) ?? 0) + 1)
  }
  return degrees
}

function isLayoutHub(node: MemoryGraphNode, degree: number): boolean {
  return degree >= 8 || (isStructuralNode(node) && degree >= 2)
}

function graphOption(options: {
  viewState?: GraphViewState | null
  forceFriction?: number
  revealedIds?: ReadonlyMap<string, number>
} = {}): MemoryGraphOption {
  const dark = $q.dark.isActive
  const currentView = captureGraphView()
  symbolZoom = options.viewState?.zoom ?? currentView?.zoom ?? 1
  allTitles.value = symbolZoom >= BRANCH_OPEN_ZOOM
  const palette = getComputedStyle(document.documentElement)
  const curvatures = parallelEdgeCurvatures()
  const degrees = graphDegrees()
  const loadedBranches = graphBranches([...nodes.value.values()], [...edges.value.values()])
  const filtered = hiddenEntityKinds.value.size > 0
  const anchors = new Set((filtered ? branches.value : loadedBranches).map(branch => branch.anchorId))
  if (!loading.value && !reloading.value && [...expandedBranches.value].some(id => !anchors.has(id))) {
    expandedBranches.value = new Set([...expandedBranches.value].filter(id => anchors.has(id)))
  }
  if (!dynamicLayout.value || hasStoredLayout.value || filtered) {
    branchLayout.update([...nodes.value.values()], loadedBranches, [...edges.value.values()])
    if (filtered && branchLayout.positions.size) hasStoredLayout.value = true
  }
  if (filtered) filteredLayout.update(visibleNodes.value, branches.value, visibleEdges.value)
  const activePositions = filtered ? filteredLayout.positions : branchLayout.positions
  previewClearance.clear()
  if (chart && activePositions.size) {
    // Local pixel buckets bound the neighbor search even with thousands of
    // loaded nodes. Only nearby centers can constrain a 320px thumbnail.
    const buckets = new Map<string, { id: string; x: number; y: number }[]>()
    const points: { id: string; x: number; y: number }[] = []
    for (const node of renderedNodes.value) {
      const point = activePositions.get(node.id)
      if (!point) continue
      const screen: unknown = chart.convertToPixel({ seriesId: GRAPH_SERIES_ID }, [point.x, point.y])
      if (!Array.isArray(screen) || !Number.isFinite(screen[0]) || !Number.isFinite(screen[1])) continue
      const projected = { id: node.id, x: screen[0] as number, y: screen[1] as number }
      points.push(projected)
      const key = `${Math.floor(projected.x / 80)},${Math.floor(projected.y / 80)}`
      if (!buckets.has(key)) buckets.set(key, [])
      buckets.get(key)!.push(projected)
    }
    for (const point of points) {
      const node = nodes.value.get(point.id)!
      if (!thumbnailKeys.has(node.id)) continue
      if (point.x < -320 || point.x > viewportSize.width + 320
        || point.y < -320 || point.y > viewportSize.height + 320) continue
      let available = 320
      for (let x = Math.floor((point.x - 332) / 80); x <= Math.floor((point.x + 332) / 80); x++) {
        for (let y = Math.floor((point.y - 332) / 80); y <= Math.floor((point.y + 332) / 80); y++) {
          for (const neighbor of buckets.get(`${x},${y}`) ?? []) {
            if (neighbor.id !== point.id) available = Math.min(available,
              Math.max(1, Math.max(Math.abs(point.x - neighbor.x), Math.abs(point.y - neighbor.y)) - 12))
          }
        }
      }
      previewClearance.set(point.id, available)
    }
  }
  // Use a data-space center: percentage centers have legacy canvas semantics
  // in ECharts and can frame outside a map with negative coordinates.
  const requestedView = options.viewState ?? currentView
  const fitting = !requestedView?.center || (requestedView.zoom ?? 1) <= MIN_ZOOM
    || requestedView.center.some(value => typeof value === 'string') && requestedView.zoom === MIN_ZOOM
  let center = requestedView?.center
  if (fitting && activePositions.size) {
    const points = [...activePositions.values()]
    center = [(Math.min(...points.map(point => point.x)) + Math.max(...points.map(point => point.x))) / 2,
      (Math.min(...points.map(point => point.y)) + Math.max(...points.map(point => point.y))) / 2]
  }
  const windowIds = new Set(visibleNodeIds.value)
  if (chart
    && Math.abs((currentView?.zoom ?? 1) - symbolZoom) < 0.000001
    && JSON.stringify(center) === JSON.stringify(currentView?.center)) {
    for (const node of visibleNodes.value) {
      const point = activePositions.get(node.id)
      if (!point) continue
      const screen: unknown = chart.convertToPixel({ seriesId: GRAPH_SERIES_ID }, [point.x, point.y])
      const branch = branchByAnchor.value.get(node.id)
      const size = nodeSymbolSize(node, branch && !expandedBranches.value.has(node.id) ? branch.memberIds.length : 0)
      const dimensions = Array.isArray(size) ? size : [size, size]
      const screenScale = 1 + (symbolZoom - 1) * NODE_SCALE_RATIO
      const halfWidth = dimensions[0]! * screenScale / 2 + 4, halfHeight = dimensions[1]! * screenScale / 2 + 4
      if (Array.isArray(screen) && (screen[0] + halfWidth < 0 || screen[0] - halfWidth > viewportSize.width
        || screen[1] + halfHeight < 0 || screen[1] - halfHeight > viewportSize.height)) windowIds.delete(node.id)
    }
  }
  const hubIds = new Set(
    visibleNodes.value
      .filter(node => isLayoutHub(node, degrees.get(node.id) ?? 0))
      .map(node => node.id),
  )
  const rootDirectoryIds = new Set(visibleNodes.value.filter(isRootDirectory).map(node => node.id))
  const labelBudget = overview.value
    ? Math.max(4, Math.min(12, Math.floor(viewportSize.width * viewportSize.height / 80_000)))
    : Math.max(4, Math.min(80, Math.floor(viewportSize.width * viewportSize.height / 20_000)))
  const labelIds = new Set(renderedNodes.value.filter(node => windowIds.has(node.id)).sort((left, right) => (
    Number(rootDirectoryIds.has(right.id)) - Number(rootDirectoryIds.has(left.id))
    || Number(hubIds.has(right.id)) - Number(hubIds.has(left.id))
    || (degrees.get(right.id) ?? 0) - (degrees.get(left.id) ?? 0)
    || activityTimestamp(right) - activityTimestamp(left)
  )).slice(0, labelBudget).map(node => node.id))
  // Force distances use map units: adapt to the canvas so ordinary windows do not
  // inherit distances tuned for a large fullscreen view.
  const forceScale = Math.min(1, Math.max(0.04, (Math.min(viewportSize.width, viewportSize.height) / 1400) ** 2))
  const seriesNodes = filtered || (dynamicLayout.value && !hasStoredLayout.value) ? visibleNodes.value : [...nodes.value.values()]
  const seriesEdges = (dynamicLayout.value && !hasStoredLayout.value && !filtered ? visibleEdges.value : renderedEdges.value)
    .filter(edge => (!dynamicLayout.value || hasStoredLayout.value)
      ? windowIds.has(edge.source_item_id) || windowIds.has(edge.target_item_id) : true)
  const edgeOpacityScale = Math.min(1, Math.sqrt(200 / Math.max(1, seriesEdges.filter(edge => (
    !collapsedMemberIds.value.has(edge.source_item_id) && !collapsedMemberIds.value.has(edge.target_item_id)
  )).length)))
  const revealed = options.revealedIds
  return {
    animation: false,
    aria: {
      enabled: true,
    },
    series: [{
      id: GRAPH_SERIES_ID,
      type: 'graph',
      // Native symbol transitions change opacity and size, never graph coordinates.
      animation: Boolean(revealed?.size),
      animationThreshold: seriesNodes.length + 1,
      animationDuration: index => revealed?.has(seriesNodes[index]?.id ?? '') ? REVEAL_DURATION_MILLISECONDS : 0,
      animationDelay: index => {
        const rank = revealed?.get(seriesNodes[index]?.id ?? '')
        return rank === undefined ? 0 : rank * REVEAL_SPREAD_MILLISECONDS / Math.max(1, (revealed?.size ?? 1) - 1)
      },
      animationEasing: 'cubicOut',
      animationDurationUpdate: 0,
      // A restored map uses explicit coordinates. Native force initialization
      // keeps its own point cache and can discard supplied fixed coordinates.
      layout: dynamicLayout.value && !hasStoredLayout.value && !filtered ? 'force' : 'none',
      preserveAspect: true,
      // ECharts treats zero as the default ratio of one. A tiny positive ratio
      // compensates the camera scale; nodeSymbolSize supplies the two sizes.
      nodeScaleRatio: NODE_SCALE_RATIO,
      labelLayout: params => ({
        hideOverlap: !rootDirectoryIds.has(seriesNodes[params.dataIndex ?? -1]?.id ?? ''),
        moveOverlap: rootDirectoryIds.has(seriesNodes[params.dataIndex ?? -1]?.id ?? '') ? 'shiftY' : undefined,
      }),
      roam: true,
      roamTrigger: 'global',
      draggable: false,
      selectedMode: 'single',
      left: 36,
      right: 36,
      top: 44,
      bottom: 44,
      center,
      zoom: Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, symbolZoom)),
      scaleLimit: {
        min: MIN_ZOOM,
        max: MAX_ZOOM,
      },
      force: {
        repulsion: [500 * forceScale, 1400 * forceScale], gravity: 0.045, friction: options.forceFriction ?? 0,
        edgeLength: [45 * Math.sqrt(forceScale), 180 * Math.sqrt(forceScale)],
        layoutAnimation: (options.forceFriction ?? 0) > 0,
      },
      // Small graphs keep folded leaves in the bounded simulation, so unveiling
      // them never changes the forces or scatters newcomers across the canvas.
      data: seriesNodes.map(node => {
        const selected = selectedNodeId.value === node.id
        const hidden = !windowIds.has(node.id) || collapsedMemberIds.value.has(node.id)
        const branch = branchByAnchor.value.get(node.id)
        const groupedCount = branch && !expandedBranches.value.has(node.id)
          ? branch.memberIds.filter(id => collapsedMemberIds.value.has(id)).length : 0
        const degree = degrees.get(node.id) ?? 0
        const geometric = node.entity_kind === 'memory' || node.entity_kind === 'topic'
          || node.entity_kind === 'contact' || node.entity_kind === 'conversation'
        const hideBorder = node.entity_kind === 'folder' || node.entity_kind === 'directory'
          || node.entity_kind === 'file' || node.entity_kind === 'attachment'
        const geometricBorderColor = palette.getPropertyValue(`--solaire-${roleAccent(node.entity_kind)}-dark`).trim()
        return {
          id: node.id,
          name: node.title,
          value: Math.sqrt(degree + 1),
          ...(!dynamicLayout.value || hasStoredLayout.value || filtered ? activePositions.get(node.id) : {}),
          fixed: dynamicLayout.value && (selected || (hasStoredLayout.value && branchLayout.positions.has(node.id))),
          symbol: hidden ? 'none' : nodeSymbol(node),
          symbolKeepAspect: !nodeThumbnailUrl(node),
          symbolSize: nodeSymbolSize(node, groupedCount),
          selected,
          itemStyle: {
            ...nodePaintStyle(node, selected, palette),
            ...(hidden ? { opacity: 0 } : {}),
            ...nodeShadowStyle.value,
          },
          label: {
            show: !hidden && (selected || allTitles.value || rootDirectoryIds.has(node.id) || labelIds.has(node.id)),
            position: 'bottom',
            distance: 5,
            color: dark ? '#f5f5f5' : '#263238',
            opacity: 1,
            fontSize: selected ? 12 : 11,
            fontWeight: selected || rootDirectoryIds.has(node.id) ? 600 : 400,
            formatter: groupedCount ? `${branch?.neighborIds?.map(id => nodeLabel(nodes.value.get(id)!)).join(' · ') ?? nodeLabel(node)}\n${t('memory.graph.branchCount', { count: groupedCount })}` : nodeLabel(node),
          },
          emphasis: {
            focus: 'adjacency',
            scale: 1.22,
            label: { show: !hidden },
            itemStyle: {
              opacity: 1,
              borderColor: geometric ? geometricBorderColor : dark ? '#ffffff' : '#263238',
              borderWidth: hideBorder ? 0 : 3,
            },
          },
          select: {
            label: { show: !hidden },
            itemStyle: {
              opacity: 1,
              borderColor: geometric ? geometricBorderColor : dark ? '#ffffff' : '#263238',
              borderWidth: hideBorder ? 0 : 4,
            },
          },
        }
      }),
      links: seriesEdges.map(edge => {
        const structural = isStructuralEdge(edge.relation_type)
        const betweenHubs = hubIds.has(edge.source_item_id) && hubIds.has(edge.target_item_id)
        const hidden = collapsedMemberIds.value.has(edge.source_item_id) || collapsedMemberIds.value.has(edge.target_item_id)
        return {
          id: edge.id,
          source: edge.source_item_id,
          target: edge.target_item_id,
          value: edge.confidence,
          ignoreForceLayout: !edge.suggested && betweenHubs,
          lineStyle: {
            ...edgePaintStyle(edge, overview.value, edgeOpacityScale, palette),
            ...(hidden ? { opacity: 0, width: 0 } : {}),
            curveness: curvatures.get(edge.id) ?? 0.22,
          },
          emphasis: {
            lineStyle: {
              opacity: hidden ? 0 : 1,
              width: reducedLinkWidth((hidden ? 0 : overview.value ? 1 : structural ? 3.2 + edge.confidence * 2 : 1.8 + edge.confidence * 1.5) * LINK_WIDTH_SCALE),
            },
          },
          blur: { lineStyle: { opacity: hidden ? 0 : 0.16 } },
        }
      }),
      lineStyle: {
        color: palette.getPropertyValue('--solaire-gray-accent').trim(),
        curveness: 0.22,
      },
      emphasis: {
        focus: 'adjacency',
        scale: true,
        lineStyle: {
          opacity: 0.95,
        },
      },
      blur: {
        label: {
          opacity: 0.55,
        },
        itemStyle: {
          opacity: 0.72,
        },
        lineStyle: {
          opacity: 0.16,
        },
      },
    }],
  }
}

function finishLayout(generation: number): void {
  if (generation !== layoutGeneration) return
  layoutPending.value = false
  chartReady.value = true
}

function captureGraphView(): GraphViewState | null {
  const instance = chart
  if (!instance) return null
  const option = instance.getOption()
  if (typeof option !== 'object' || option === null) return null
  const series = Reflect.get(option, 'series')
  if (!Array.isArray(series)) return null
  for (const candidate of series as unknown[]) {
    if (
      typeof candidate !== 'object'
      || candidate === null
      || Reflect.get(candidate, 'id') !== GRAPH_SERIES_ID
    ) continue
    const zoom = Reflect.get(candidate, 'zoom')
    return {
      center: Reflect.get(candidate, 'center') as GraphSeriesOption['center'],
      zoom: typeof zoom === 'number' ? zoom : undefined,
    }
  }
  return null
}

function applyPreferences(preferences: GraphPreferences): void {
  hiddenEntityKinds.value = new Set(preferences.hidden_entity_kinds)
  expandedBranches.value = new Set(preferences.expanded_branches)
  threeCamera = preferences.camera_3d ?? null
  restoredCamera = preferences.camera ? {
    center: preferences.camera.center ?? ['50%', '50%'], zoom: Math.max(MIN_ZOOM, preferences.camera.zoom),
  } : null
  const zoom = preferences.camera?.zoom ?? 1
  overview.value = zoom <= 1.2
  allTitles.value = zoom >= BRANCH_OPEN_ZOOM
}

function displayedPositions(): Map<string, ScreenPoint> {
  const points = new Map(branchLayout.positions)
  const data = chart ? graphViewportData(chart) : undefined
  if (data) for (let index = 0; index < data.count(); index++) {
    const key = data.getId(index)
    if (!nodes.value.has(key)) continue
    const point: unknown = data.getItemLayout(index)
    if (Array.isArray(point) && typeof point[0] === 'number' && typeof point[1] === 'number'
      && Number.isFinite(point[0]) && Number.isFinite(point[1])) points.set(key, { x: point[0], y: point[1] })
  }
  return points
}

function stagePositions(): void {
  if (!persistence || !chartReady.value) return
  persistence.stagePositions(branchLayout.positions)
}

function freezePositions(): void {
  if (viewMode.value === '3d') return
  if (!chart || !chartReady.value || loading.value || reloading.value || !nodes.value.size) return
  // Type filters have their own compact layout. Never replace the saved full
  // map with coordinates from a temporary filtered view.
  if (hiddenEntityKinds.value.size) return
  for (const [key, point] of displayedPositions()) branchLayout.positions.set(key, point)
  branchLayout.update([...nodes.value.values()], graphBranches([...nodes.value.values()], [...edges.value.values()]), [...edges.value.values()])
  hasStoredLayout.value = true
  stagePositions()
}

function samplePositions(): void {
  if (!chart || !chartReady.value || loading.value || reloading.value || hasStoredLayout.value
    || hiddenEntityKinds.value.size || !nodes.value.size) return
  const points = displayedPositions()
  if (!points.size) return
  const stable = points.size === previousPositionSample.size && [...points].every(([key, point]) => {
    const previous = previousPositionSample.get(key)
    return previous && Math.hypot(previous.x - point.x, previous.y - point.y) < 0.25
  })
  stablePositionSamples = stable ? stablePositionSamples + 1 : 0
  previousPositionSample = points
  if (stablePositionSamples < 2) return
  freezePositions()
  renderGraph({ viewState: captureGraphView(), preserveSelection: true, relax: false })
}

function scheduleViewSave(): void {
  registerSaveTimeout(() => { void persistence?.flush() }, 600)
}

function stagePresentation(): void {
  if (viewMode.value === '3d') {
    if (persistence && threeScene && threeHasMap && !loading.value && !reloading.value) {
      threeCamera = threeScene.view
      persistence.stagePreferences({ expanded_branches: [...expandedBranches.value], camera_3d: threeCamera })
      scheduleViewSave()
    }
    return
  }
  if (!persistence || !chart || loading.value || reloading.value) return
  const view = captureGraphView()
  if (!view) return
  const center = view?.center
  const camera = view?.zoom ? {
    center: Array.isArray(center) && typeof center[0] === 'number' && typeof center[1] === 'number'
      ? [center[0], center[1]] as [number, number] : null,
    zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.zoom)),
  } : null
  persistence.stagePreferences({ expanded_branches: [...expandedBranches.value], camera })
  scheduleViewSave()
}

async function retryViewState(): Promise<void> {
  const current = persistence
  if (!current) return
  try {
    const preferences = await current.load()
    if (current !== persistence) return
    applyPreferences(preferences)
    renderGraph({ viewState: restoredCamera, preserveSelection: true, relax: false })
    await current.flush()
  } catch (failure) {
    if (current === persistence) viewStateError.value = failure
  }
}

function stopGraphLayout(): void {
  removeLayoutTimeout()
  const wasEnabled = layoutRelaxationEnabled
  layoutRelaxationEnabled = false
  if (wasEnabled && dynamicLayout.value && nodes.value.size) {
    chart?.setOption({ series: [{ id: GRAPH_SERIES_ID, force: { friction: 0, layoutAnimation: false } }] })
  }
}

function renderGraph(options: {
  viewState?: GraphViewState | null
  preserveSelection?: boolean
  relax?: boolean
} = {}): void {
  if (viewMode.value === '3d') { void renderGraph3d(); return }
  const instance = chart
  if (!instance) return
  const previousView = captureGraphView()
  const generation = ++layoutGeneration
  removeLayoutTimeout()
  layoutRelaxationEnabled = false
  layoutPending.value = visibleNodes.value.length > 0 && (loading.value || !chartReady.value)
  if (visibleNodes.value.length === 0) chartReady.value = true
  if (!options.preserveSelection) closeInspector(false)
  const animate = dynamicLayout.value && !hasStoredLayout.value && !hiddenEntityKinds.value.size
    && renderedNodes.value.length > 0 && options.relax !== false
  const rebalancing = hasLayoutStarted
  const renderedIds = new Set(renderedNodes.value.map(node => node.id))
  const reveal = options.relax === false && lastRenderedIds.size > 0
    && renderedIds.size <= MAX_ANIMATED_VISIBLE_NODES
    && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ? new Map([...renderedIds].filter(id => !lastRenderedIds.has(id) && id !== selectedNodeId.value)
      .map((id, rank) => [id, rank])) : undefined
  instance.setOption(graphOption({
    viewState: options.viewState,
    forceFriction: animate ? hasLayoutStarted ? 0.12 : 0.35 : 0,
    revealedIds: reveal,
  }), {
    notMerge: false,
  })
  // A direct group click or restored camera changes the transform during the
  // update. Apply its viewport window only after that transform exists.
  if ((!dynamicLayout.value || hasStoredLayout.value || hiddenEntityKinds.value.size)
    && (options.viewState?.zoom !== previousView?.zoom
      || JSON.stringify(options.viewState?.center) !== JSON.stringify(previousView?.center))) {
    instance.setOption(graphOption({ viewState: captureGraphView(), forceFriction: 0 }), { notMerge: false })
  }
  lastRenderedIds = renderedIds
  if (animate) {
    hasLayoutStarted = true
    layoutRelaxationEnabled = true
    // Initial placement converges naturally. Only actual graph updates use a
    // short rebalance; presentation changes always keep the reached positions.
    if (rebalancing) registerLayoutTimeout(() => {
      if (chart !== instance || generation !== layoutGeneration) return
      stopGraphLayout()
    }, LAYOUT_REBALANCE_MILLISECONDS)
  }
  if (renderFrame !== null) cancelAnimationFrame(renderFrame)
  renderFrame = requestAnimationFrame(() => {
    renderFrame = null
    finishLayout(generation)
    scheduleThumbnails()
    if (!animate) { stagePositions(); scheduleViewSave() }
  })
}

async function loadInitial(options: { preserveView?: boolean } = {}): Promise<void> {
  const preserveView = options.preserveView === true
  const preservedSelection = preserveView ? selectedNodeId.value : null
  if (preserveView && threeScene && threeHasMap) threeCamera = threeScene.view
  if (!preserveView) {
    freezePositions()
    stagePresentation()
    void persistence?.flush()
    removeSaveTimeout()
    persistence = null
  }
  const generation = ++loadGeneration
  rootController?.abort()
  const controller = new AbortController()
  rootController = controller
  thumbnails.clear()
  threeScene?.setPreviews(new Map())
  threeScene?.setData([], [], [], false)
  cancelThreeLayout?.()
  threeLayout = null
  threeLayoutKey = []
  threePoints.clear()
  spatialGroupedCount.value = 0
  threeHasMap = false
  threeRenderGeneration++
  thumbnailResources.clear()
  thumbnailKeys.clear()
  removeThumbnailTimeout()
  if (!preserveView) thumbnailsNear = false
  layoutGeneration += 1
  stopGraphLayout()
  nodes.value = new Map()
  edges.value = new Map()
  selectedNodeId.value = preservedSelection
  edgesTruncated.value = false
  error.value = null
  if (!preserveView) chartReady.value = agentId === null
  if (!preserveView) {
    hasLayoutStarted = false
    lastRenderedIds = new Set()
    branchLayout.clear()
    filteredLayout.clear()
    hasStoredLayout.value = false
    hiddenEntityKinds.value = new Set()
    previousPositionSample = new Map()
    stablePositionSamples = 0
    restoredCamera = null
    threeCamera = null
    viewStateError.value = null
    expandedBranches.value = new Set()
    overview.value = false
    allTitles.value = false
  }
  layoutPending.value = false
  if (!preserveView) chart?.clear()
  if (agentId === null) {
    threeScene?.dispose()
    threeScene = null
    chart?.dispose()
    chart = null
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
    while (loadNextPage) {
      const page = await memoryService.listGraphRoots({
        agentId,
        query,
        topicItemId,
        contactItemId,
        limit: ROOT_PAGE_SIZE,
        edgeLimit: 2500,
        cursor,
        includeMatchingRoots: true,
        includeSavedPositions: true,
        signal: controller.signal,
      })
      if (generation !== loadGeneration) return
      mergeRootPage(page)
      loadNextPage = page.has_more && page.next_cursor !== null
      cursor = page.next_cursor
    }
    if (selectedNodeId.value !== null && !nodes.value.has(selectedNodeId.value)) {
      selectedNodeId.value = null
    }
    await nextTick()
    await initializeRenderer()
    renderGraph({
      viewState: preserveView ? captureGraphView() : restoredCamera,
      preserveSelection: preserveView,
    })
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
    }
  }
}

function reload(): void {
  void loadInitial({ preserveView: true })
}

function invalidateAccess(): void {
  freezePositions()
  stagePresentation()
  nodes.value = new Map()
  edges.value = new Map()
  closeInspector()
  chart?.clear()
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

async function refreshLatestRoots(): Promise<void> {
  if (
    !liveRefresh.value
    || agentId === null
    || loading.value
    || reloading.value
    || refreshing.value
    || document.visibilityState !== 'visible'
  ) return
  const generation = loadGeneration
  refreshing.value = true
  try {
    const page = await memoryService.listGraphRoots({
      agentId,
      query,
      topicItemId,
      contactItemId,
      limit: ROOT_PAGE_SIZE,
      edgeLimit: 2500,
      includeMatchingRoots: true,
      includeSavedPositions: true,
      signal: rootController?.signal,
    })
    if (generation !== loadGeneration) return
    if (!graphPageHasChanges(page)) { scheduleThumbnails(); return }
    freezePositions()
    mergeRootPage(page)
    edgesTruncated.value = edgesTruncated.value || page.edges_truncated
    renderGraph({
      viewState: captureGraphView(),
      preserveSelection: true,
    })
  } catch {
    // The regular reload button owns visible error reporting.
  } finally {
    refreshing.value = false
  }
}

function selectNode(id: string): void {
  const node = nodes.value.get(id)
  if (!node || !isNodeVisible(node)) return
  const wasCollapsed = collapsedMemberIds.value.has(id)
  selectedNodeId.value = id
  if (viewMode.value === '3d') {
    threeScene?.setSelected(id)
    void renderGraph3d().then(() => threeScene?.focus(id))
  }
  if (wasCollapsed || dynamicLayout.value) renderGraph({ viewState: captureGraphView(), preserveSelection: true, relax: false })
  chart?.dispatchAction({
    type: 'select',
    seriesId: GRAPH_SERIES_ID,
    dataId: id,
  })
  if (node.node_kind !== 'folder' && node.node_kind !== 'conversation') {
    emit('open', id, node, selectedRelations.value)
  }
}

function closeInspector(render = true): void {
  if (selectedNodeId.value === null) return
  const selectedId = selectedNodeId.value
  selectedNodeId.value = null
  threeScene?.setSelected(null)
  chart?.dispatchAction({
    type: 'unselect',
    seriesId: GRAPH_SERIES_ID,
  })
  if (render && (dynamicLayout.value || overview.value || collapsedMemberIds.value.has(selectedId))) {
    renderGraph({ viewState: captureGraphView(), preserveSelection: true, relax: false })
  }
}

defineExpose({ selectNode, closeDetails: closeInspector })

function eventNodeId(event: ECElementEvent): string | null {
  if (event.dataType !== 'node' || typeof event.data !== 'object' || event.data === null) {
    return null
  }
  const id = Reflect.get(event.data, 'id')
  return typeof id === 'string' ? id : null
}

function eventAnchor(event: ECElementEvent): ScreenPoint {
  return {
    x: event.event?.offsetX ?? viewportSize.width / 2,
    y: event.event?.offsetY ?? viewportSize.height / 2,
  }
}

function onGraphClick(event: ECElementEvent): void {
  const id = eventNodeId(event)
  if (!id) return
  if (branchByAnchor.value.has(id) && !expandedBranches.value.has(id)) {
    revealBranch(id, eventAnchor(event))
    return
  }
  if ($q.screen.lt.md) {
    const zrEvent = event.event
    if (zrEvent?.zrByTouch) {
      zrEvent.event.preventDefault()
      zrEvent.event.stopPropagation()
    }
    const generation = loadGeneration
    registerMobileDetailTimeout(() => {
      if (generation === loadGeneration) selectNode(id)
    }, MOBILE_DETAIL_OPEN_DELAY)
    return
  }
  selectNode(id)
}

function resizeChart(): void {
  const container = viewport.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  const changed = viewportSize.width !== Math.floor(rect.width) || viewportSize.height !== Math.floor(rect.height)
  viewportSize.width = Math.max(1, Math.floor(rect.width))
  viewportSize.height = Math.max(1, Math.floor(rect.height))
  if (viewMode.value === '3d') { threeScene?.resize(); scheduleThumbnails(); return }
  chart?.resize()
  scheduleThumbnails()
  // A toolbar wrapping during zoom may resize the canvas. Continue enabled
  // physics, but never restart a layout frozen by a presentation change.
  if (changed && chart && nodes.value.size && !layoutRelaxationEnabled) {
    renderGraph({ viewState: captureGraphView(), preserveSelection: true, relax: false })
  }
}

function fitGraph(): void {
  if (viewMode.value === '3d') {
    expandedBranches.value = new Set()
    closeInspector(false)
    void renderGraph3d().then(() => threeScene?.fit())
    return
  }
  if (!chart || !visibleNodes.value.length) return
  freezePositions()
  closeInspector(false)
  expandedBranches.value = new Set()
  overview.value = true
  allTitles.value = false
  renderGraph({ viewState: { center: ['50%', '50%'], zoom: 1 }, preserveSelection: true, relax: false })
  stagePresentation()
}

function zoomBy(scaleFactor: number): void {
  if (viewMode.value === '3d') { threeScene?.zoomBy(scaleFactor); return }
  if (!chart) return
  chart.dispatchAction({
    type: 'graphRoam',
    seriesId: GRAPH_SERIES_ID,
    zoom: scaleFactor,
    originX: viewportSize.width / 2,
    originY: viewportSize.height / 2,
  })
}

function onGraphPinch(event: ElementEvent): void {
  if (!chart || !window.matchMedia(MOBILE_GRAPH_MEDIA_QUERY).matches) return

  Reflect.set(event, '__ecRoamConsumed', true)
  event.stop()

  if (!Number.isFinite(event.pinchScale) || event.pinchScale <= 0 || event.pinchScale === 1) {
    return
  }

  chart.dispatchAction({
    type: 'graphRoam',
    seriesId: GRAPH_SERIES_ID,
    zoom: Math.pow(event.pinchScale, MOBILE_PINCH_ZOOM_SENSITIVITY),
    originX: event.pinchX,
    originY: event.pinchY,
  })
}

function initializeChart(): void {
  const element = chartElement.value
  if (!element || chart) return
  chart = echarts.init(element, undefined, {
    renderer: 'canvas',
    devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
  })
  // Switching from 3D already has positions. Establish the public coordinate
  // system before graphOption projects them through the new ECharts instance.
  chart.setOption({ series: [{ id: GRAPH_SERIES_ID, type: 'graph', layout: 'none', data: [], links: [] }] })
  chart.on('click', onGraphClick)
  chart.on('graphRoam', onGraphRoam)
  chart.getZr().on('pinch', onGraphPinch)
  chart.getZr().on('click', event => {
    if (!event.target) closeInspector()
  })
  resizeChart()
  renderGraph()
}

async function initializeRenderer(): Promise<void> {
  if (threeDisposed || agentId === null) return
  resizeObserver?.disconnect()
  if (viewport.value) resizeObserver?.observe(viewport.value)
  if (viewMode.value === '2d') { initializeChart(); return }
  if (threeScene) return
  if (threeInitializing) return threeInitializing
  threeInitializing = (async () => {
    try {
      const { MemoryGraphScene } = await import('../graph3dScene')
      if (threeDisposed || viewMode.value !== '3d' || !threeElement.value) return
      threeScene = new MemoryGraphScene(threeElement.value, {
        groupTitle: count => t('memory.graph.spatialGroup', { count }),
        camera: onThreeCamera,
        select: id => {
          if (branchByAnchor.value.has(id) && !expandedBranches.value.has(id)) revealBranch(id)
          else selectNode(id)
        },
        failure: () => {
          threeUnavailable.value = true
          threeScene?.dispose()
          threeScene = null
          void changeViewMode('2d')
        },
      })
      threeUnavailable.value = false
      await renderGraph3d()
    } catch {
      threeUnavailable.value = true
      await changeViewMode('2d')
    }
  })().finally(() => { threeInitializing = null })
  return threeInitializing
}

async function changeViewMode(mode: '2d' | '3d'): Promise<void> {
  if (mode === viewMode.value && (mode === '3d' ? threeScene : chart)) return
  freezePositions()
  stagePresentation()
  viewMode.value = mode
  threeScene?.suspend(mode === '2d')
  if (mode === '3d') stopGraphLayout()
  await nextTick()
  await initializeRenderer()
  resizeChart()
  renderGraph({ viewState: mode === '2d' ? captureGraphView() ?? restoredCamera : undefined, preserveSelection: true, relax: false })
  scheduleThumbnails()
}

async function renderGraph3d(fit = false): Promise<void> {
  const instance = threeScene
  if (!instance || viewMode.value !== '3d') return
  const generation = ++threeRenderGeneration
  const key = [nodes.value, edges.value, hiddenEntityKinds.value]
  if (key.some((value, index) => value !== threeLayoutKey[index])) {
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
          void changeViewMode('2d')
        }
      }
      worker.postMessage({ generation, nodes: visibleNodes.value, edges: visibleEdges.value,
        branches: branches.value, positions: [...layout.positions],
        depths: [...threePoints].map(([id, point]) => [id, point.z]) })
    })
  }
  let result: Graph3dLayoutResult | null
  try {
    result = await threeLayout
  } catch {
    if (generation !== threeRenderGeneration || threeDisposed) return
    layoutPending.value = false
    threeUnavailable.value = true
    await changeViewMode('2d')
    return
  }
  if (!result || generation !== threeRenderGeneration || threeScene !== instance || viewMode.value !== '3d') return
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
    return [{ id: node.id, title: grouped ? `${node.title} (${t('memory.graph.branchCount', { count: grouped })})` : node.title, point, grouped,
      ...paint, selectedBorderColor: nodePaintStyle(node, true, palette).borderColor,
      symbol: nodeSymbol(node, false), size: nodeBaseSymbolSize(node, grouped),
      shape: node.entity_kind === 'memory' ? 0 : node.entity_kind === 'topic' ? 1 : 2,
      priority: node.id === selectedNodeId.value ? 100 : grouped ? 30 : isStructuralNode(node) || isRootDirectory(node) ? 10 : 0 }]
  })
  instance.setTheme($q.dark.isActive ? solaire.gray.dark : solaire.gray.light,
    $q.dark.isActive ? solaire.gray.light : solaire.gray.dark)
  const edgeOpacityScale = Math.min(1, Math.sqrt(200 / Math.max(1, renderedEdges.value.length)))
  const curvatures = parallelEdgeCurvatures()
  instance.setData(markers, renderedEdges.value.map(edge => {
    const detail = edgePaintStyle(edge, false, edgeOpacityScale, palette)
    const overview = edgePaintStyle(edge, true, edgeOpacityScale, palette)
    return { source: edge.source_item_id, target: edge.target_item_id, ...detail, type: edge.relation_type,
      width: detail.width * 1.25, curvature: curvatures.get(edge.id) ?? 0.22,
      overviewStyle: { width: overview.width * 2.25, opacity: overview.opacity }, suggested: edge.suggested }
  }),
  markers.map(marker => marker.point), fit || !threeHasMap)
  if (!threeHasMap && threeCamera && !fit) instance.restore(threeCamera)
  threeHasMap = markers.length > 0
  instance.setSelected(selectedNodeId.value)
  layoutPending.value = false
  chartReady.value = true
  if (!hiddenEntityKinds.value.size) {
    hasStoredLayout.value = true
    stagePositions()
    scheduleViewSave()
  }
  scheduleThumbnails()
}

function onThreeCamera(): void {
  const instance = threeScene
  if (!instance || !threeHasMap || viewMode.value !== '3d' || loading.value || reloading.value) return
  spatialGroupedCount.value = instance.groupedCount
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
}

function updateThreeThumbnails(): void {
  const instance = threeScene
  if (!instance || agentId === null || viewMode.value !== '3d') return
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
  threeScene?.setSymbols(new Map(renderedNodes.value.map(node => [node.id, nodeSymbol(node, false)])))
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
    removeMobileDetailTimeout()
    void loadInitial()
  },
  { immediate: true },
)

watch(
  () => $q.dark.isActive,
  () => renderGraph({ viewState: captureGraphView(), preserveSelection: true, relax: false }),
)

onMounted(() => {
  websocket.createWebsocket()
  websocket.onEvent('memory', 'invalidate', invalidateAccess)
  websocket.onConnect(invalidateAccess)
  void initializeRenderer()
  resizeObserver = new ResizeObserver(resizeChart)
  if (viewport.value) resizeObserver.observe(viewport.value)
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, onGraphSessionChange)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  registerInterval(() => {
    void refreshLatestRoots()
  }, AUTO_REFRESH_INTERVAL)
  registerPositionInterval(samplePositions, 1_000)
})

onUnmounted(() => {
  freezePositions()
  stagePresentation()
  void persistence?.flush()
  persistence = null
  threeDisposed = true
  threeRenderGeneration++
  cancelThreeLayout?.()
  threeWorker?.terminate()
  threeScene?.dispose()
  threeScene = null
  removeSaveTimeout()
  removePositionInterval()
  unsubscribeThumbnailReady()
  thumbnails.clear()
  thumbnailResources.clear()
  if (thumbnailPaintTimer !== null) clearTimeout(thumbnailPaintTimer)
  if (thumbnailFrame !== null) cancelAnimationFrame(thumbnailFrame)
  websocket.offEvent('memory', 'invalidate', invalidateAccess)
  websocket.offConnect(invalidateAccess)
  loadGeneration += 1
  rootController?.abort()
  layoutGeneration += 1
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
  chart?.getZr().off('pinch', onGraphPinch)
  chart?.dispose()
  if (renderFrame !== null) cancelAnimationFrame(renderFrame)
  chart = null
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
  padding: 2px 3px 2px 8px;
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

.memory-graph__view-controls {
  padding: 3px;
  border-radius: 999px;
  background: rgba(25, 118, 210, 0.06);
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

.memory-graph__chart,
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

.memory-graph__chart:focus-visible,
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

.memory-graph--dark .memory-graph__view-controls {
  background: rgba(144, 202, 249, 0.08);
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
