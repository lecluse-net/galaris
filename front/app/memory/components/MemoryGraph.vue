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

    <q-banner
      v-if="capacityReached"
      class="memory-graph__banner memory-graph__banner--info bg-blue-1 text-primary"
    >
      <template #avatar><q-icon name="account_tree" /></template>
      {{ t('memory.graph.capacityReached', { count: MAX_VISIBLE_NODES }) }}
    </q-banner>

    <div
      v-if="agentId !== null"
      class="memory-graph__legend-panel"
      role="group"
      :aria-label="t('memory.graph.legend')"
    >
      <section class="memory-graph__legend-group">
        <div class="memory-graph__legend-title">{{ t('memory.graph.typeLegend') }}</div>
        <div class="memory-graph__legend-items">
          <q-btn
            v-for="type in MEMORY_TYPE_LEGEND"
            :key="type"
            flat
            dense
            no-caps
            class="memory-graph__legend-item memory-graph__type-filter"
            :class="{ 'memory-graph__type-filter--hidden': isMemoryTypeHidden(type) }"
            :aria-label="nodeTypeToggleLabel(t(`memory.types.${type}`), isMemoryTypeHidden(type))"
            :aria-pressed="!isMemoryTypeHidden(type)"
            @click="toggleMemoryType(type)"
          >
            <span
              class="memory-graph__type-legend-dot"
              :style="{ backgroundColor: nodeColor(type) }"
              aria-hidden="true"
            />
            {{ t(`memory.types.${type}`) }}
            <q-icon v-if="isMemoryTypeHidden(type)" name="visibility_off" size="12px" />
            <q-tooltip>
              {{ nodeTypeToggleLabel(t(`memory.types.${type}`), isMemoryTypeHidden(type)) }}
            </q-tooltip>
          </q-btn>
        </div>
      </section>

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
            <span
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
          <span>{{ t('memory.graph.older') }}</span>
          <span class="memory-graph__gradient" />
          <span>{{ t('memory.graph.recent') }}</span>
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
          ref="chartElement"
          class="memory-graph__chart"
          :class="{ 'memory-graph__chart--loading': graphBusy }"
          role="img"
          tabindex="0"
          :aria-label="t('memory.graph.canvasLabel')"
        />

        <div v-if="!graphBusy && visibleNodes.length === 0" class="memory-graph__empty">
          <q-icon name="hub" size="48px" color="grey-5" />
          <div class="text-body2 text-grey-7 q-mt-sm">{{ t('memory.graph.empty') }}</div>
        </div>

        <q-inner-loading :showing="graphBusy">
          <q-spinner-orbit color="primary" size="42px" />
        </q-inner-loading>

        <q-card
          v-if="selectedNode"
          flat
          bordered
          class="memory-graph__inspector"
          :style="inspectorStyle"
          @pointerdown.stop
          @dblclick.stop
          @wheel.stop
        >
          <MemoryGraphNodeDetail
            :agent-id="agentId"
            :node="selectedNode"
            :relations="selectedRelations"
            :color="nodeColor(selectedNode.memory_type)"
            :icon="nodeIcon(selectedNode)"
            :role-label="nodeRoleLabel(selectedNode)"
            @close="closeInspector"
            @open="openNodeDetail"
            @select="selectNode"
          />
        </q-card>
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
import { solaireCss } from '@/core/util'
import { useInterval, useQuasar, useTimeout } from 'quasar'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { AriaComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ECElementEvent, ECharts, EChartsCoreOption, ElementEvent } from 'echarts/core'
import type { GraphSeriesOption } from 'echarts/charts'
import MemoryGraphNodeDetail from './MemoryGraphNodeDetail.vue'
import { memoryService } from '../services/memoryService'
import type {
  MemoryGraphCursor,
  MemoryGraphEdge,
  MemoryGraphEntityKind,
  MemoryGraphNode,
  MemoryGraphPage,
  MemoryType,
} from '../types'

interface SelectedRelation {
  edge: MemoryGraphEdge
  other: MemoryGraphNode
}

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

echarts.use([GraphChart, AriaComponent, CanvasRenderer])

const {
  agentId,
  query,
  memoryTypes,
  topicItemId,
  contactItemId,
  timeRangeMilliseconds,
} = defineProps<{
  agentId: number | null
  query: string
  memoryTypes: MemoryType[]
  topicItemId: string | null
  contactItemId: string | null
  timeRangeMilliseconds: number | null
}>()

const emit = defineEmits<{
  open: [id: string]
}>()

const ROOT_PAGE_SIZE = 100
const MAX_VISIBLE_NODES = 3000
const MAX_VISIBLE_EDGES = 8000
const AUTO_REFRESH_INTERVAL = 30_000
const MIN_ZOOM = 0.2
const MAX_ZOOM = 4
const MOBILE_GRAPH_MEDIA_QUERY = '(max-width: 1023px)'
const MOBILE_PINCH_ZOOM_SENSITIVITY = 0.35
const MOBILE_DETAIL_OPEN_DELAY = 50
const GRAPH_SERIES_ID = 'memory-graph'
const MEMORY_TYPE_LEGEND: readonly MemoryType[] = [
  'core',
  'working',
  'episodic',
  'semantic',
  'procedural',
  'social',
]
const GRAPH_ROLE_LEGEND: readonly MemoryGraphEntityKind[] = [
  'topic',
  'contact',
  'document',
  'attachment',
  'folder',
  'conversation',
]
const NODE_COLORS_LIGHT: Record<MemoryType, string> = {
  core: '#7e57c2',
  working: '#fb8c00',
  episodic: '#1e88e5',
  semantic: '#00897b',
  procedural: '#3949ab',
  social: '#d81b60',
}

const NODE_COLORS_DARK: Record<MemoryType, string> = {
  core: '#b39ddb',
  working: '#ffb74d',
  episodic: '#64b5f6',
  semantic: '#4db6ac',
  procedural: '#7986cb',
  social: '#f06292',
}

const EDGE_COLORS_LIGHT = {
  topic: '#00897b',
  contact: '#d81b60',
  topicContact: '#8e24aa',
  default: '#607d8b',
} as const

const EDGE_COLORS_DARK = {
  topic: '#4db6ac',
  contact: '#f06292',
  topicContact: '#ce93d8',
  default: '#b0bec5',
} as const

const { t } = useI18n()
const $q = useQuasar()
const { registerInterval, removeInterval } = useInterval()
const { registerTimeout: registerMobileDetailTimeout } = useTimeout()
const viewport = useTemplateRef<HTMLDivElement>('viewport')
const chartElement = useTemplateRef<HTMLDivElement>('chartElement')
const nodes = shallowRef(new Map<string, MemoryGraphNode>())
const edges = shallowRef(new Map<string, MemoryGraphEdge>())
const hiddenMemoryTypes = shallowRef(new Set<MemoryType>())
const hiddenEntityKinds = shallowRef(new Set<MemoryGraphEntityKind>())
const selectedNodeId = ref<string | null>(null)
const edgesTruncated = ref(false)
const capacityReached = ref(false)
const loading = ref(false)
const reloading = ref(false)
const refreshing = ref(false)
const liveRefresh = ref(true)
const rangeEndTimestamp = ref(Date.now())
const error = ref<unknown>(null)
const isFullscreen = ref(false)
const layoutPending = ref(false)
const chartReady = ref(false)
const viewportSize = reactive({ width: 0, height: 0 })
const inspectorAnchor = reactive<ScreenPoint>({ x: 0, y: 0 })

let resizeObserver: ResizeObserver | null = null
let chart: ECharts | null = null
let previousBodyOverflow: string | null = null
let loadGeneration = 0
let layoutGeneration = 0

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
const selectedNode = computed(() => {
  if (selectedNodeId.value === null) return null
  const node = nodes.value.get(selectedNodeId.value)
  return node && isNodeVisible(node) ? node : null
})

const graphBusy = computed(() => loading.value || layoutPending.value || !chartReady.value)
const timeRangeStartTimestamp = computed<number | null>(() => {
  return timeRangeMilliseconds === null
    ? null
    : rangeEndTimestamp.value - timeRangeMilliseconds
})
const inspectorStyle = computed<Record<string, string | undefined>>(() => {
  const node = selectedNode.value
  if (!node) return {}
  const margin = 12
  const gap = 18
  const width = Math.min(360, Math.max(240, viewportSize.width - margin * 2))
  const maxHeight = Math.min(520, Math.max(180, viewportSize.height - margin * 2))
  const point = inspectorAnchor
  if (viewportSize.width < 600) {
    return {
      right: `${margin}px`,
      bottom: `${margin}px`,
      left: `${margin}px`,
      maxHeight: `${Math.min(maxHeight, viewportSize.height * 0.55)}px`,
    }
  }
  const radius = radiusFor(node)
  const preferredRight = point.x + radius + gap
  const left = preferredRight + width <= viewportSize.width - margin
    ? preferredRight
    : point.x - radius - gap - width
  return {
    left: `${Math.max(margin, Math.min(viewportSize.width - width - margin, left))}px`,
    top: `${Math.max(
      margin,
      Math.min(viewportSize.height - maxHeight - margin, point.y - maxHeight / 2),
    )}px`,
    width: `${width}px`,
    maxHeight: `${maxHeight}px`,
  }
})

const activityExtent = computed(() => {
  const timestamps = visibleNodes.value
    .map(node => Date.parse(node.activity_at))
    .filter(Number.isFinite)
  return {
    newest: timestamps.length ? Math.max(...timestamps) : 0,
    oldest: timestamps.length ? Math.min(...timestamps) : 0,
  }
})

const selectedRelations = computed<SelectedRelation[]>(() => {
  if (selectedNodeId.value === null) return []
  const relations: SelectedRelation[] = []
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

function nodeColor(type: MemoryType): string {
  return ($q.dark.isActive ? NODE_COLORS_DARK : NODE_COLORS_LIGHT)[type]
}

function roleColor(role: MemoryGraphEntityKind): string {
  switch (role) {
    case 'attachment': return solaireCss.cyan.accent
    case 'folder': return solaireCss.yellow.accent
    case 'contact': return nodeColor('social')
    case 'document': return nodeColor('working')
    case 'conversation': return nodeColor('episodic')
    default: return nodeColor('semantic')
  }
}

function isMemoryTypeHidden(type: MemoryType): boolean {
  return hiddenMemoryTypes.value.has(type)
}

function isEntityKindHidden(kind: MemoryGraphEntityKind): boolean {
  return hiddenEntityKinds.value.has(kind)
}

function isNodeVisible(node: MemoryGraphNode): boolean {
  if (node.entity_kind === 'memory') {
    return !isMemoryTypeHidden(node.memory_type)
  }
  return !isEntityKindHidden(node.entity_kind)
}

function nodeTypeToggleLabel(label: string, hidden: boolean): string {
  return t(hidden ? 'memory.graph.showNodeType' : 'memory.graph.hideNodeType', { type: label })
}

function renderTypeFilterChange(): void {
  if (selectedNodeId.value !== null && selectedNode.value === null) closeInspector()
  renderGraph({
    viewState: captureGraphView(),
    preserveSelection: true,
  })
}

function toggleMemoryType(type: MemoryType): void {
  const next = new Set(hiddenMemoryTypes.value)
  if (next.has(type)) next.delete(type)
  else next.add(type)
  hiddenMemoryTypes.value = next
  renderTypeFilterChange()
}

function toggleEntityKind(kind: MemoryGraphEntityKind): void {
  const next = new Set(hiddenEntityKinds.value)
  if (next.has(kind)) next.delete(kind)
  else next.add(kind)
  hiddenEntityKinds.value = next
  renderTypeFilterChange()
}

function nodeIcon(node: MemoryGraphNode): string {
  switch (node.entity_kind) {
    case 'topic': return 'topic'
    case 'contact': return 'person'
    case 'document': return 'description'
    case 'attachment':
      if (node.resource_media_type?.startsWith('image/')) return 'image'
      if (node.resource_media_type?.startsWith('audio/')) return 'audio_file'
      if (node.resource_media_type?.startsWith('video/')) return 'video_file'
      return 'attach_file'
    case 'folder': return 'folder'
    case 'conversation': return 'forum'
    default: return 'neurology'
  }
}

function nodeRoleLabel(node: MemoryGraphNode): string {
  if (node.entity_kind === 'memory') return t(`memory.types.${node.memory_type}`)
  return t(`memory.graph.roles.${node.entity_kind}`)
}

function nodeSymbol(node: MemoryGraphNode): 'circle' | 'diamond' | 'rect' | 'roundRect' {
  switch (node.entity_kind) {
    case 'topic': return 'diamond'
    case 'contact': return 'roundRect'
    case 'document': return 'rect'
    case 'attachment': return 'rect'
    case 'folder': return 'roundRect'
    case 'conversation': return 'roundRect'
    default: return 'circle'
  }
}

function isStructuralNode(node: MemoryGraphNode): boolean {
  return node.entity_kind === 'topic' || node.entity_kind === 'contact'
}

function edgeColor(relationType: string): string {
  const palette = $q.dark.isActive ? EDGE_COLORS_DARK : EDGE_COLORS_LIGHT
  if (relationType === 'topic_involves_contact') return palette.topicContact
  if (relationType === 'contact_contains') return palette.contact
  if (relationType === 'topic_contains' || relationType.startsWith('topic_')) return palette.topic
  return palette.default
}

function isStructuralEdge(relationType: string): boolean {
  return relationType === 'topic_contains'
    || relationType === 'contact_contains'
    || relationType === 'topic_involves_contact'
}

function activityTimestamp(node: MemoryGraphNode): number {
  const timestamp = Date.parse(node.activity_at)
  return Number.isFinite(timestamp) ? timestamp : Date.parse(node.created_at)
}

function freshness(node: MemoryGraphNode): number {
  const timestamp = activityTimestamp(node)
  const { newest, oldest } = activityExtent.value
  if (!Number.isFinite(timestamp) || newest <= oldest) return 1
  const age = Math.max(0, newest - timestamp)
  const range = Math.max(1, newest - oldest)
  const relative = 1 - Math.log1p(age) / Math.log1p(range)
  return 0.08 + Math.max(0, Math.min(1, relative)) * 0.92
}

function radiusFor(node: MemoryGraphNode): number {
  const roleBoost = node.entity_kind === 'topic'
    ? 6
    : node.entity_kind === 'contact'
      ? 4
      : node.entity_kind === 'document'
        ? 2
        : 0
  return 8 + freshness(node) * 8 + roleBoost + (selectedNodeId.value === node.id ? 3 : 0)
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
    if (next.size >= MAX_VISIBLE_NODES) {
      capacityReached.value = true
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
    if (!next.has(edge.id) && next.size >= MAX_VISIBLE_EDGES) {
      edgesTruncated.value = true
      continue
    }
    next.set(edge.id, edge)
  }
  edges.value = next
}

function mergeRootPage(page: MemoryGraphPage): void {
  mergeNodes(page.nodes)
  mergeEdges(page.edges)
  edgesTruncated.value = edgesTruncated.value || page.edges_truncated
}

function pageWithinTimeRange(
  page: MemoryGraphPage,
  cutoffTimestamp: number | null,
): MemoryGraphPage {
  if (cutoffTimestamp === null) return page
  const filteredNodes = page.nodes.filter(node => activityTimestamp(node) >= cutoffTimestamp)
  const visibleIds = new Set([
    ...nodes.value.keys(),
    ...filteredNodes.map(node => node.id),
  ])
  return {
    ...page,
    nodes: filteredNodes,
    edges: page.edges.filter(edge => (
      visibleIds.has(edge.source_item_id) && visibleIds.has(edge.target_item_id)
    )),
  }
}

function pageCanContainMoreVisibleRoots(
  page: MemoryGraphPage,
  cutoffTimestamp: number | null,
): boolean {
  if (!page.has_more || page.next_cursor === null) return false
  if (cutoffTimestamp === null) return true
  return Date.parse(page.next_cursor.activity_at) >= cutoffTimestamp
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

function pruneOutsideTimeRange(cutoffTimestamp: number | null): boolean {
  if (cutoffTimestamp === null) return false
  const retainedNodes = new Map(
    [...nodes.value.entries()].filter(([_id, node]) => (
      activityTimestamp(node) >= cutoffTimestamp
    )),
  )
  if (retainedNodes.size === nodes.value.size) return false
  nodes.value = retainedNodes
  edges.value = new Map(
    [...edges.value.entries()].filter(([_id, edge]) => (
      retainedNodes.has(edge.source_item_id) && retainedNodes.has(edge.target_item_id)
    )),
  )
  return true
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
  return node.title.length > 28 ? `${node.title.slice(0, 27)}…` : node.title
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
} = {}): MemoryGraphOption {
  const dark = $q.dark.isActive
  const curvatures = parallelEdgeCurvatures()
  const degrees = graphDegrees()
  const hubIds = new Set(
    visibleNodes.value
      .filter(node => isLayoutHub(node, degrees.get(node.id) ?? 0))
      .map(node => node.id),
  )
  const layoutAnimation = visibleNodes.value.length > 180
  return {
    animation: false,
    aria: {
      enabled: true,
    },
    series: [{
      id: GRAPH_SERIES_ID,
      type: 'graph',
      layout: 'force',
      roam: true,
      roamTrigger: 'global',
      draggable: false,
      selectedMode: 'single',
      left: 36,
      right: 36,
      top: 44,
      bottom: 44,
      center: options.viewState?.center,
      zoom: options.viewState?.zoom,
      scaleLimit: {
        min: MIN_ZOOM,
        max: MAX_ZOOM,
      },
      force: {
        repulsion: [500, 1400],
        gravity: 0.045,
        friction: 0.6,
        edgeLength: [50, 200],
        layoutAnimation,
      },
      data: visibleNodes.value.map(node => {
        const freshnessScore = freshness(node)
        const selected = selectedNodeId.value === node.id
        const degree = degrees.get(node.id) ?? 0
        return {
          id: node.id,
          name: node.title,
          value: Math.sqrt(degree + 1),
          symbol: nodeSymbol(node),
          symbolSize: radiusFor(node) * 2,
          selected,
          itemStyle: {
            color: node.entity_kind === 'attachment' || node.entity_kind === 'folder'
              ? getComputedStyle(document.documentElement).getPropertyValue(`--solaire-${node.entity_kind === 'attachment' ? 'cyan' : 'yellow'}-accent`).trim()
              : nodeColor(node.memory_type),
            opacity: 1,
            borderColor: selected
              ? (dark ? '#ffffff' : '#263238')
              : isStructuralNode(node)
                ? (dark ? '#ffffff' : '#263238')
                : node.source_managed
                  ? '#90caf9'
                  : 'rgba(255, 255, 255, 0.9)',
            borderWidth: selected ? 4 : isStructuralNode(node) ? 3 : node.source_managed ? 2 : 1.5,
            shadowColor: nodeColor(node.memory_type),
            shadowBlur: freshnessScore * 18 + (isStructuralNode(node) ? 8 : 0),
          },
          label: {
            show: true,
            position: 'bottom',
            distance: 5,
            color: dark ? '#f5f5f5' : '#263238',
            opacity: Math.max(0.65, freshnessScore),
            fontSize: selected ? 12 : 11,
            fontWeight: selected ? 600 : 400,
            formatter: nodeLabel(node),
          },
          emphasis: {
            focus: 'adjacency',
            scale: 1.22,
            itemStyle: {
              opacity: 1,
              borderColor: dark ? '#ffffff' : '#263238',
              borderWidth: 3,
            },
          },
          select: {
            itemStyle: {
              borderColor: dark ? '#ffffff' : '#263238',
              borderWidth: 4,
            },
          },
        }
      }),
      links: visibleEdges.value.map(edge => {
        const structural = isStructuralEdge(edge.relation_type)
        return {
          id: edge.id,
          source: edge.source_item_id,
          target: edge.target_item_id,
          value: edge.confidence,
          ignoreForceLayout: !edge.suggested
            && hubIds.has(edge.source_item_id)
            && hubIds.has(edge.target_item_id),
          lineStyle: {
            color: edgeColor(edge.relation_type),
            opacity: edge.suggested ? 0.38 : structural ? 0.86 : 0.62,
            width: edge.suggested
              ? 0.8 + edge.confidence
              : structural
                ? 2 + edge.confidence * 1.8
                : 0.9 + edge.confidence * 1.4,
            curveness: curvatures.get(edge.id) ?? 0.22,
            type: edge.suggested ? 'dashed' : 'solid',
          },
          emphasis: {
            lineStyle: {
              opacity: 1,
              width: structural ? 3.2 + edge.confidence * 2 : 1.8 + edge.confidence * 1.5,
            },
          },
        }
      }),
      lineStyle: {
        color: dark ? EDGE_COLORS_DARK.default : EDGE_COLORS_LIGHT.default,
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

function renderGraph(options: {
  viewState?: GraphViewState | null
  preserveSelection?: boolean
} = {}): void {
  const instance = chart
  if (!instance) return
  const generation = ++layoutGeneration
  layoutPending.value = visibleNodes.value.length > 0
  chartReady.value = visibleNodes.value.length === 0
  if (!options.preserveSelection) closeInspector()
  instance.clear()
  const onFinished = (): void => {
    instance.off('finished', onFinished)
    finishLayout(generation)
  }
  instance.on('finished', onFinished)
  instance.setOption(graphOption({
    viewState: options.viewState,
  }), {
    notMerge: true,
  })
  if (visibleNodes.value.length <= 180) {
    requestAnimationFrame(() => finishLayout(generation))
  }
}

async function loadInitial(options: { preserveView?: boolean } = {}): Promise<void> {
  const preserveView = options.preserveView === true
  const preservedSelection = preserveView ? selectedNodeId.value : null
  const generation = ++loadGeneration
  layoutGeneration += 1
  nodes.value = new Map()
  edges.value = new Map()
  selectedNodeId.value = preservedSelection
  edgesTruncated.value = false
  capacityReached.value = false
  error.value = null
  if (!preserveView) chartReady.value = agentId === null
  layoutPending.value = false
  if (!preserveView) chart?.clear()
  if (agentId === null) {
    return
  }

  if (preserveView) {
    reloading.value = true
  } else {
    loading.value = true
  }
  rangeEndTimestamp.value = Date.now()
  const cutoffTimestamp = timeRangeStartTimestamp.value
  try {
    let cursor: MemoryGraphCursor | null = null
    let loadNextPage = true
    while (loadNextPage) {
      const page = await memoryService.listGraphRoots({
        agentId,
        query,
        memoryTypes,
        topicItemId,
        contactItemId,
        limit: ROOT_PAGE_SIZE,
        edgeLimit: 500,
        cursor,
        knownItemIds: [...nodes.value.keys()].slice(-500),
      })
      if (generation !== loadGeneration) return
      mergeRootPage(pageWithinTimeRange(page, cutoffTimestamp))
      loadNextPage = pageCanContainMoreVisibleRoots(page, cutoffTimestamp)
      cursor = page.next_cursor
      if (loadNextPage && nodes.value.size >= MAX_VISIBLE_NODES) {
        capacityReached.value = true
        loadNextPage = false
      }
    }
    if (selectedNodeId.value !== null && !nodes.value.has(selectedNodeId.value)) {
      selectedNodeId.value = null
    }
    await nextTick()
    renderGraph({
      viewState: preserveView ? captureGraphView() : null,
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
  nodes.value = new Map()
  edges.value = new Map()
  closeInspector()
  chart?.clear()
  void loadInitial()
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
  const refreshedAt = Date.now()
  const milliseconds = timeRangeMilliseconds
  const cutoffTimestamp = milliseconds === null ? null : refreshedAt - milliseconds
  try {
    const page = await memoryService.listGraphRoots({
      agentId,
      query,
      memoryTypes,
      topicItemId,
      contactItemId,
      limit: ROOT_PAGE_SIZE,
      edgeLimit: 500,
      knownItemIds: [...nodes.value.keys()].slice(-500),
    })
    if (generation !== loadGeneration) return
    rangeEndTimestamp.value = refreshedAt
    const visiblePage = pageWithinTimeRange(page, cutoffTimestamp)
    const pageChanged = graphPageHasChanges(visiblePage)
    const pruned = pruneOutsideTimeRange(cutoffTimestamp)
    const changed = pageChanged || pruned
    if (!changed) return
    mergeNodes(visiblePage.nodes)
    mergeEdges(visiblePage.edges)
    edgesTruncated.value = edgesTruncated.value || visiblePage.edges_truncated
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

function selectNode(id: string, anchor?: ScreenPoint): void {
  if (!nodes.value.has(id)) return
  selectedNodeId.value = id
  inspectorAnchor.x = anchor?.x ?? viewportSize.width / 2
  inspectorAnchor.y = anchor?.y ?? viewportSize.height / 2
  chart?.dispatchAction({
    type: 'select',
    seriesId: GRAPH_SERIES_ID,
    dataId: id,
  })
}

function closeInspector(): void {
  if (selectedNodeId.value === null) return
  selectedNodeId.value = null
  chart?.dispatchAction({
    type: 'unselect',
    seriesId: GRAPH_SERIES_ID,
  })
}

function openNodeDetail(id: string): void {
  if ($q.screen.lt.md) closeInspector()
  emit('open', id)
}

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
  const node = nodes.value.get(id)
  if ($q.screen.lt.md && node && node.node_kind !== 'conversation' && node.node_kind !== 'folder') {
    const zrEvent = event.event
    if (zrEvent?.zrByTouch) {
      zrEvent.event.preventDefault()
      zrEvent.event.stopPropagation()
    }
    registerMobileDetailTimeout(() => {
      const currentNode = nodes.value.get(id)
      if (currentNode && currentNode.node_kind !== 'conversation' && currentNode.node_kind !== 'folder') emit('open', id)
    }, MOBILE_DETAIL_OPEN_DELAY)
    return
  }
  selectNode(id, eventAnchor(event))
}

function resizeChart(): void {
  const container = viewport.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  viewportSize.width = Math.max(1, Math.floor(rect.width))
  viewportSize.height = Math.max(1, Math.floor(rect.height))
  chart?.resize()
}

function fitGraph(): void {
  if (!chart || !visibleNodes.value.length) return
  closeInspector()
  chart.setOption({
    series: [{
      id: GRAPH_SERIES_ID,
      center: null,
      zoom: 1,
    }],
  })
}

function zoomBy(scaleFactor: number): void {
  if (!chart) return
  closeInspector()
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

  closeInspector()
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
  chart.on('click', onGraphClick)
  chart.on('graphRoam', closeInspector)
  chart.getZr().on('pinch', onGraphPinch)
  chart.getZr().on('click', event => {
    if (!event.target) closeInspector()
  })
  resizeChart()
  renderGraph()
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
    () => memoryTypes.join('|'),
    () => topicItemId,
    () => contactItemId,
    () => timeRangeMilliseconds,
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
  websocket.onConnect(invalidateAccess)
  initializeChart()
  resizeObserver = new ResizeObserver(resizeChart)
  if (viewport.value) resizeObserver.observe(viewport.value)
  window.addEventListener('keydown', onKeyDown)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  registerInterval(() => {
    void refreshLatestRoots()
  }, AUTO_REFRESH_INTERVAL)
})

onUnmounted(() => {
  websocket.offEvent('memory', 'invalidate', invalidateAccess)
  websocket.offConnect(invalidateAccess)
  loadGeneration += 1
  layoutGeneration += 1
  resizeObserver?.disconnect()
  removeInterval()
  window.removeEventListener('keydown', onKeyDown)
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

.memory-graph--fullscreen .memory-graph__viewport,
.memory-graph--fullscreen .memory-graph__inspector {
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
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 7px;
  padding: 8px 10px;
  background: #fff;
  color: #455a64;
  font-size: 11px;
}

.memory-graph__legend-group {
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid rgba(69, 90, 100, 0.13);
  border-radius: 8px;
  background: rgba(96, 125, 139, 0.035);
}

.memory-graph__legend-group--view {
  display: flex;
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

.memory-graph__chart {
  display: block;
  width: 100%;
  height: 100%;
  outline: none;
  transition: opacity 120ms ease-out;
}

.memory-graph__chart--loading {
  opacity: 0;
}

.memory-graph__chart:focus-visible {
  box-shadow: inset 0 0 0 3px var(--q-primary);
}

.memory-graph__gradient {
  width: 64px;
  height: 8px;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(0, 137, 123, 0.22), rgba(0, 137, 123, 1));
}

.memory-graph__empty {
  position: absolute;
  top: 50%;
  left: 50%;
  text-align: center;
  transform: translate(-50%, -50%);
}

.memory-graph__inspector {
  position: absolute;
  z-index: 2;
  min-width: 0;
  padding: 20px;
  overflow-y: auto;
  cursor: default;
  user-select: text;
  box-shadow: 0 12px 36px rgba(38, 50, 56, 0.22);
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

.memory-graph--dark .memory-graph__gradient {
  background: linear-gradient(90deg, rgba(144, 202, 249, 0.16), #90caf9);
}

.memory-graph--dark .memory-graph__inspector {
  background: #1d2027;
  border-color: rgba(255, 255, 255, 0.14);
  box-shadow: 0 14px 42px rgba(0, 0, 0, 0.48);
}

@media (max-width: 1199px) {
  .memory-graph__legend-panel {
    grid-template-columns: repeat(2, minmax(0, 1fr));
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
    grid-template-columns: minmax(0, 1fr);
    padding: 7px;
  }

  .memory-graph__legend-group--view {
    flex-wrap: wrap;
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
