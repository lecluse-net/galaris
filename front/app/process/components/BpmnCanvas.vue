<template>
  <section class="diagram-editor" :class="{ fullscreen: isFullscreen, readonly }" :aria-label="t('nativeProcesses.diagram')">
    <div class="diagram-toolbar">
      <div v-if="showGuide" class="diagram-guide"><q-icon name="touch_app" size="18px" />{{ t(readonly ? 'nativeProcesses.diagramReadHint' : 'nativeProcesses.handleHint') }}</div>
      <div class="row items-center q-gutter-sm">
        <slot v-if="!readonly" name="toolbar-actions" />
        <q-btn v-if="!readonly" outline color="warning" icon="auto_fix_high" :label="t('nativeProcesses.arrange')" @click="arrange" />
        <GraphViewControls>
          <q-btn outline round dense color="primary" icon="add" :aria-label="t('nativeProcesses.zoomIn')" :disable="zoom >= 1.5" @click="zoom = Math.min(1.5, zoom + .1)">
            <q-tooltip>{{ t('nativeProcesses.zoomIn') }}</q-tooltip>
          </q-btn>
          <q-btn outline round dense color="primary" icon="remove" :aria-label="t('nativeProcesses.zoomOut')" :disable="zoom <= .2" @click="zoom = Math.max(.2, zoom - .1)">
            <q-tooltip>{{ t('nativeProcesses.zoomOut') }}</q-tooltip>
          </q-btn>
          <q-btn outline round dense color="primary" icon="fit_screen" :aria-label="t('nativeProcesses.fitDiagram')" @click="fit">
            <q-tooltip>{{ t('nativeProcesses.fitDiagram') }}</q-tooltip>
          </q-btn>
          <q-btn flat dense color="primary" :label="`${Math.round(zoom * 100)}%`" :aria-label="t('nativeProcesses.resetZoom')" @click="zoom = 1">
            <q-tooltip>{{ t('nativeProcesses.resetZoom') }}</q-tooltip>
          </q-btn>
          <q-btn round dense color="primary" :icon="isFullscreen ? 'fullscreen_exit' : 'fullscreen'" :aria-label="t(isFullscreen ? 'nativeProcesses.exitFullscreen' : 'nativeProcesses.fullscreen')"
            :aria-pressed="isFullscreen" :loading="fullscreenBusy" @click="toggleFullscreen">
            <q-tooltip>{{ t(isFullscreen ? 'nativeProcesses.exitFullscreen' : 'nativeProcesses.fullscreen') }}</q-tooltip>
          </q-btn>
        </GraphViewControls>
      </div>
    </div>
    <div ref="scroll" class="bpmn-scroll" @keydown.esc="connecting = null; cancelDrag()">
      <div class="diagram-scale" :style="{ width: `${width * zoom}px`, height: `${height * zoom}px` }">
        <div class="diagram-board" :style="{ width: `${width}px`, height: `${height}px`, transform: `scale(${zoom})` }" @pointermove="move" @pointerup="stop" @pointercancel="cancelDrag">
          <div v-for="lane in lanes" :key="lane" class="swimlane" :class="{ 'human-lane': actor(lane)?.kind === 'human', 'drop-allowed': drag?.moved && dropTarget?.lane === lane && dropTarget.allowed || laneDrag?.moved && laneDrag.id === lane, 'drop-forbidden': drag?.moved && dropTarget?.lane === lane && !dropTarget.allowed }"
            :style="{ top: `${layout.lanes.indexOf(lane) * layout.laneHeight}px`, height: `${layout.laneHeight}px`, width: `${width}px` }">
            <ProcessLaneHeader :actor="actor(lane) ?? null" :readonly="readonly" :used="modelValue.nodes.some(node => node.config.actor === lane)"
              :assignment="assignment(lane)" :agents="agents" :humans="humans" :humans-loading="humansLoading" :humans-error="humansError" :execution-agent-id="executionAgentId === undefined ? modelValue.execution_agent_id : executionAgentId" :execution-editable="executionEditable"
              @update="updateActor(lane, $event)" @remove="removeActor(lane)" @execution="emit('update:executionAgentId', $event)"
              @reload-humans="emit('reloadHumans')"
              @reorder-start="beginLaneDrag($event, lane)" @reorder-cancel="cancelLaneDrag" @reorder="shiftActor(lane, $event)" />
          </div>
          <svg class="flow-surface" :width="width" :height="height" :viewBox="`0 0 ${width} ${height}`" aria-hidden="true">
            <defs><marker :id="arrowId" viewBox="0 0 10 10" markerWidth="8" markerHeight="8" refX="9" refY="5" orient="auto"><path d="M0 0 L10 5 L0 10 Z" /></marker></defs>
            <g v-for="flow in modelValue.flows" :key="flow.id" class="flow" :class="{ 'flow-selected': selectedFlow === flow.id }">
              <path class="flow-line" :d="flowPath(flow)" :marker-end="`url(#${arrowId})`" />
            </g>
            <path v-if="linkDrag?.moved" class="flow-line connection-preview" :d="connectionPreviewPath" :marker-end="`url(#${arrowId})`" />
          </svg>
          <button v-for="flow in modelValue.flows" :key="flow.id" class="flow-label" :class="{ conditional: flow.condition && !modelValue.nodes.find(node => node.id === flow.source)?.config.mode, selected: selectedFlow === flow.id }"
            :style="{ left: `${flowMidpoint(flow).x}px`, top: `${flowMidpoint(flow).y}px` }" :aria-label="t('nativeProcesses.flow', { source: flow.source, target: flow.target })" @click="emit('flow', flow.id)">
            {{ modelValue.nodes.find(node => node.id === flow.source)?.config.mode ? t(flow.condition === null ? 'nativeProcesses.falseBranch' : 'nativeProcesses.trueBranch') : flow.condition || t('nativeProcesses.editFlow') }}
            <q-menu v-if="selectedFlow === flow.id && $slots.inspector" :model-value="true" no-parent-event anchor="bottom middle" self="top middle" :offset="[0, 12]"
              class="process-context-form" max-height="min(420px, 60vh)" role="dialog" :aria-label="t('nativeProcesses.flowSettings')"
              @update:model-value="value => { if (!value) emit('dismiss', 'flow', flow.id) }">
              <slot name="inspector" />
            </q-menu>
          </button>
          <div v-for="node in modelValue.nodes" :key="node.id" class="node-wrap" :class="[node.kind, statusClass(node.id), { selected: selected === node.id, dragging: drag?.id === node.id && drag.moved, 'invalid-drop': drag?.id === node.id && drag.moved && !dropTarget?.allowed }]"
            :data-process-node="node.id" :style="{ left: `${position(node).x}px`, top: `${position(node).y}px`, width: `${nodeWidth(node)}px` }">
            <button class="node-card" :class="{ 'connect-target': connecting && canConnect(node) }" :aria-label="`${node.title || t('nativeProcesses.kinds.' + node.kind)} · ${node.id}`" :aria-pressed="selected === node.id" :aria-current="['running', 'waiting'].includes(statuses[node.id] ?? '') ? 'step' : undefined"
              @pointerdown="begin($event, node.id)" @lostpointercapture="cancelDrag" @keydown="key($event, node.id)" @click="choose(node.id)">
              <span class="node-symbol"><q-icon :name="nodeIcons[node.kind]" :size="isEvent(node) ? '28px' : isGateway(node) ? '22px' : '14px'" /></span>
              <span v-if="!isEvent(node) && !isGateway(node)" class="node-copy"><strong>{{ node.title || t('nativeProcesses.untitledActivity') }}</strong><span class="node-kind">{{ t('nativeProcesses.kinds.' + node.kind) }}</span></span>
              <span v-if="node.body" class="body-indicator"><q-icon name="add_box" size="16px" /></span>
              <q-menu v-if="selected === node.id && $slots.inspector && !drag?.moved" :model-value="true" no-parent-event anchor="bottom middle" self="top middle" :offset="[0, 12]"
                class="process-context-form process-activity-form" :max-height="readonly ? 'min(520px, 70vh)' : 'min(420px, 60vh)'" role="dialog" :aria-label="inspectorLabel || t('nativeProcesses.activitySettings')"
                @update:model-value="value => { if (!value) emit('dismiss', 'node', node.id) }">
                <slot name="inspector" />
              </q-menu>
            </button>
            <div v-if="isEvent(node) || isGateway(node)" class="event-title">{{ node.title || t('nativeProcesses.kinds.' + node.kind) }}</div>
            <span v-if="statuses[node.id]" class="node-badge" role="status"><q-icon v-if="['running', 'waiting'].includes(statuses[node.id] ?? '')" :name="statuses[node.id] === 'running' ? 'play_circle' : 'hourglass_top'" size="14px" class="q-mr-xs" />{{ t(`processes.statuses.${statuses[node.id]}`, statuses[node.id]!) }}</span>
            <template v-if="!readonly">
              <button v-for="port in ports(node)" :key="`${port.side}-${port.outcome}`"
                class="port" :class="[port.side, { 'output-true': port.outcome === true, 'output-false': port.outcome === false }]" :aria-label="t(port.outcome === true ? 'nativeProcesses.trueOutput' : port.outcome === false ? 'nativeProcesses.falseOutput' : port.side === 'input' ? 'nativeProcesses.inputHandle' : 'nativeProcesses.outputHandle', { title: node.title || t('nativeProcesses.kinds.' + node.kind) })"
                :data-flow-port="port.side" @pointerdown.stop="beginLink($event, node.id, port.side, port.outcome)" @lostpointercapture="cancelLink"
                @click.capture="portClick" @keydown.stop @keydown.esc.prevent="connecting = null; cancelDrag()">
                <span v-if="port.outcome !== undefined" class="port-outcome">{{ t(port.outcome ? 'nativeProcesses.trueBranch' : 'nativeProcesses.falseBranch') }}</span>
                <q-menu anchor="bottom middle" self="top middle" class="handle-menu">
                  <q-list style="min-width: 240px">
                    <q-item-label header>{{ t(port.side === 'input' ? 'nativeProcesses.insertBefore' : 'nativeProcesses.continueFlow') }}</q-item-label>
                    <q-item v-for="kind in activityKinds.filter(kind => kind !== 'end' || port.side === 'output' && !adjacent(node.id, port.side, port.outcome).length)" :key="kind" clickable v-close-popup
                      :disable="kind === 'human_task' && !modelValue.actors?.some(actor => actor.kind === 'human')" @click="add(node.id, port.side, kind, false, port.outcome)">
                      <q-item-section avatar><q-icon :name="nodeIcons[kind]" /></q-item-section><q-item-section>{{ t('nativeProcesses.kinds.' + kind) }}</q-item-section>
                    </q-item>
                    <q-separator />
                    <q-item clickable v-close-popup @click="connecting = { id: node.id, side: port.side, outcome: port.outcome }"><q-item-section avatar><q-icon name="link" /></q-item-section><q-item-section>{{ t('nativeProcesses.connect') }}</q-item-section></q-item>
                    <template v-if="port.side === 'output' && port.outcome === undefined && adjacent(node.id, port.side).length">
                      <q-item clickable><q-item-section avatar><q-icon name="call_split" /></q-item-section><q-item-section>{{ t('nativeProcesses.addBranch') }}</q-item-section>
                        <q-menu anchor="top end" self="top start"><q-list><q-item v-for="kind in activityKinds" :key="kind" clickable v-close-popup
                          :disable="kind === 'human_task' && !modelValue.actors?.some(actor => actor.kind === 'human')" @click="add(node.id, port.side, kind, true)"><q-item-section>{{ t('nativeProcesses.kinds.' + kind) }}</q-item-section></q-item></q-list></q-menu>
                      </q-item>
                    </template>
                    <q-item v-for="flow in adjacent(node.id, port.side, port.outcome)" :key="flow.id" clickable v-close-popup @click="emit('flow', flow.id)"><q-item-section avatar><q-icon name="edit" /></q-item-section><q-item-section>{{ t('nativeProcesses.flow', { source: title(flow.source), target: title(flow.target) }) }}</q-item-section></q-item>
                  </q-list>
                </q-menu>
              </button>
            </template>
            <div v-if="overlays[node.id]" class="overlay">{{ overlays[node.id] }}</div>
          </div>
        </div>
      </div>
    </div>
    <div v-if="!readonly" class="new-actor-zone" :class="{ active: drag?.moved && dropTarget?.create }" :aria-label="t('nativeProcesses.dropToCreateActor')">
      <q-btn outline rounded color="primary" class="q-ml-sm" :label="t('nativeProcesses.newActor')">
        <q-menu><q-list>
          <q-item v-for="kind in ['agent', 'human'] as const" :key="kind" clickable v-close-popup @click="addActor(kind)">
            <q-item-section avatar><q-icon :name="kind === 'agent' ? 'smart_toy' : 'person'" /></q-item-section>
            <q-item-section>{{ t(kind === 'agent' ? 'nativeProcesses.addAgentActor' : 'nativeProcesses.addHumanActor') }}</q-item-section>
          </q-item>
        </q-list></q-menu>
      </q-btn>
      <q-tooltip>{{ t('nativeProcesses.dropToCreateActor') }}</q-tooltip>
    </div>
    <div v-if="connecting" role="status" class="connect-hint"><q-icon name="link" />{{ t('nativeProcesses.connectTarget') }}<q-btn flat dense :label="t('nativeProcesses.cancelConnection')" @click="connecting = null" /></div>
    <div v-if="drag?.moved && dropTarget?.create" role="status" class="drop-message"><q-icon name="group_add" />{{ t('nativeProcesses.dropToCreateActor') }}</div>
    <div v-if="dropError" role="status" class="drop-message"><q-icon name="block" />{{ t('nativeProcesses.incompatibleActorDrop') }}</div>
    <Teleport to="body">
      <div v-if="drag?.moved && draggedNode" class="node-wrap drag-preview selected" :class="[draggedNode.kind, statusClass(draggedNode.id), { 'invalid-drop': !dropTarget?.allowed }]" :style="dragPreviewStyle" aria-hidden="true">
        <div class="node-card">
          <span class="node-symbol"><q-icon :name="nodeIcons[draggedNode.kind]" :size="isEvent(draggedNode) ? '28px' : isGateway(draggedNode) ? '22px' : '14px'" /></span>
          <span v-if="!isEvent(draggedNode) && !isGateway(draggedNode)" class="node-copy"><strong>{{ draggedNode.title || t('nativeProcesses.untitledActivity') }}</strong><span class="node-kind">{{ t('nativeProcesses.kinds.' + draggedNode.kind) }}</span></span>
          <span v-if="draggedNode.body" class="body-indicator"><q-icon name="add_box" size="16px" /></span>
        </div>
        <div v-if="isEvent(draggedNode) || isGateway(draggedNode)" class="event-title">{{ draggedNode.title || t('nativeProcesses.kinds.' + draggedNode.kind) }}</div>
        <span v-if="statuses[draggedNode.id]" class="node-badge">{{ t(`processes.statuses.${statuses[draggedNode.id]}`, statuses[draggedNode.id]!) }}</span>
        <template v-if="!readonly">
          <span v-for="side in draggedNode.kind === 'start' ? ['output'] : draggedNode.kind === 'end' ? ['input'] : ['input', 'output']" :key="side" class="port" :class="side" />
        </template>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, shallowRef, useId, watch, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { GraphViewControls } from '@/core/util'
import type { BpmnGraph, BpmnNode, BpmnFlow, NodeKind, ProcessActor, ProcessAgentOption } from '../services/nativeProcessService'
import { activityKinds, nodeIcons, graphLayout, insertActivity, canConnectActivities, connectActivities, assignActivityActor, laneHeaderWidth, nodeStartX } from '../graphEditing'
import ProcessLaneHeader from './ProcessLaneHeader.vue'
const props = withDefaults(defineProps<{ modelValue: BpmnGraph; readonly?: boolean; showGuide?: boolean; autoFit?: boolean; inspectorLabel?: string; selected?: string | null; selectedFlow?: string | null;
  agents?: ProcessAgentOption[]; humans?: { id: number; label: string }[];
  humansLoading?: boolean; humansError?: boolean;
  executionAgentId?: number | null; executionEditable?: boolean;
  statuses?: Record<string, string>; overlays?: Record<string, string> }>(), { readonly: false, showGuide: true, selected: null, selectedFlow: null, executionEditable: false, agents: () => [], humans: () => [], statuses: () => ({}), overlays: () => ({}) })
const emit = defineEmits<{ 'update:modelValue': [graph: BpmnGraph]; 'update:executionAgentId': [id: number | null]; reloadHumans: []; select: [id: string]; flow: [id: string]; remove: [id: string]; dismiss: [kind: 'node' | 'flow', id: string] }>()
const { t } = useI18n()
const arrowId = `bpmn-arrow-${useId()}`
const scroll = ref<HTMLDivElement>(), zoom = ref(1)
const viewportWidth = ref(0)
let viewportObserver: ResizeObserver | undefined
const isFullscreen = ref(false), fullscreenBusy = ref(false)
let previousBodyOverflow: string | null = null, ownsNativeFullscreen = false, disposed = false
const connecting = ref<{ id: string; side: 'input' | 'output'; outcome?: boolean } | null>(null)
const linkDrag = shallowRef<{ id: string; side: 'input' | 'output'; outcome?: boolean; pointer: number; element: HTMLElement;
  origin: { x: number; y: number }; point: { x: number; y: number }; target: string | null; moved: boolean } | null>(null)
let blockedPortClick: { element: HTMLElement; until: number } | null = null
const drag = shallowRef<{ id: string; dx: number; dy: number; pointer: number; element: HTMLElement; origin: { x: number; y: number }; preview: { x: number; y: number }; moved: boolean; outside: boolean } | null>(null)
const laneDrag = shallowRef<{ id: string; pointer: number; element: HTMLElement; originY: number; target: number; moved: boolean } | null>(null)
const dropError = ref(false)
const lanes = computed(() => ['', ...(props.modelValue.actors ?? []).map(actor => actor.id)])
const layout = computed(() => graphLayout(laneDrag.value?.moved ? { ...props.modelValue, actors: orderedActors(laneDrag.value.id, laneDrag.value.target) } : props.modelValue,
  Object.values(props.overlays).some(Boolean) ? 52 : 0))
const horizontalOffset = computed(() => { const saved = props.modelValue.nodes.filter(node => node.x > 0); return saved.length ? Math.max(0, nodeStartX - Math.min(...saved.map(node => node.x))) : 0 })
const isEvent = (node: BpmnNode): boolean => node.kind === 'start' || node.kind === 'end'
const isGateway = (node: BpmnNode): boolean => node.kind === 'if' || node.kind === 'parallel'
const nodeWidth = (node: BpmnNode): number => isEvent(node) ? 72 : isGateway(node) ? 88 : 200
const draggedNode = computed(() => props.modelValue.nodes.find(node => node.id === drag.value?.id))
const dragPreviewStyle = computed(() => {
  const current = drag.value, node = draggedNode.value, viewport = scroll.value
  if (!current || !node || !viewport) return {}
  const bounds = viewport.getBoundingClientRect()
  return {
    left: `${bounds.left + current.preview.x * zoom.value - viewport.scrollLeft}px`,
    top: `${bounds.top + current.preview.y * zoom.value - viewport.scrollTop}px`,
    width: `${nodeWidth(node)}px`, transform: `scale(${zoom.value})`,
    '--diagram-surface': getComputedStyle(viewport).getPropertyValue('--diagram-surface'),
  }
})
function actor(id: string) { return props.modelValue.actors?.find(actor => actor.id === id) }
function makeActor(kind: 'agent' | 'human'): ProcessActor {
  let number = (props.modelValue.actors?.length ?? 0) + 1
  while (props.modelValue.actors?.some(actor => actor.name === t('nativeProcesses.newActorNumber', { number }))) number++
  return { id: 'actor_' + crypto.randomUUID().replaceAll('-', '').slice(0, 12), name: t('nativeProcesses.newActorNumber', { number }), kind, agent_id: null, user_id: null }
}
function addActor(kind: 'agent' | 'human'): void { if (!props.readonly) emit('update:modelValue', { ...props.modelValue, actors: [...(props.modelValue.actors ?? []), makeActor(kind)] }) }
function updateActor(id: string, patch: Partial<ProcessActor>): void {
  if (props.readonly) return
  emit('update:modelValue', { ...props.modelValue, actors: (props.modelValue.actors ?? []).map(actor => actor.id === id ? { ...actor,
    ...(patch.name !== undefined ? { name: patch.name } : {}),
    ...(actor.kind === 'agent' && patch.agent_id !== undefined ? { agent_id: patch.agent_id } : {}),
    ...(actor.kind === 'human' && patch.user_id !== undefined ? { user_id: patch.user_id } : {}) } : actor) })
}
function removeActor(id: string): void {
  if (!props.readonly && !props.modelValue.nodes.some(node => node.config.actor === id)) emit('update:modelValue', { ...props.modelValue, actors: (props.modelValue.actors ?? []).filter(actor => actor.id !== id) })
}
function orderedActors(id: string, target: number): ProcessActor[] {
  const actors = [...(props.modelValue.actors ?? [])], from = actors.findIndex(actor => actor.id === id)
  if (from < 0) return actors
  const [actor] = actors.splice(from, 1)
  actors.splice(Math.max(0, Math.min(actors.length, target)), 0, actor!)
  return actors
}
function shiftActor(id: string, direction: -1 | 1): void {
  if (props.readonly || drag.value || laneDrag.value) return
  const actors = props.modelValue.actors ?? [], index = actors.findIndex(actor => actor.id === id), target = index + direction
  if (index >= 0 && target >= 0 && target < actors.length) emit('update:modelValue', { ...props.modelValue, actors: orderedActors(id, target) })
}
function beginLaneDrag(event: PointerEvent, id: string): void {
  const index = props.modelValue.actors?.findIndex(actor => actor.id === id) ?? -1
  if (props.readonly || connecting.value || linkDrag.value || drag.value || laneDrag.value || event.button !== 0 || index < 0) return
  const element = event.currentTarget as HTMLElement
  element.focus({ preventScroll: true })
  laneDrag.value = { id, pointer: event.pointerId, element, originY: event.clientY, target: index, moved: false }
  element.setPointerCapture(event.pointerId)
}
function cancelLaneDrag(): void {
  const current = laneDrag.value
  laneDrag.value = null
  if (current?.element.hasPointerCapture(current.pointer)) current.element.releasePointerCapture(current.pointer)
}
function assignment(id: string): string {
  const item = actor(id)
  if (!item) return t('nativeProcesses.orchestrationHint')
  return (item.kind === 'agent' ? props.agents.find(agent => agent.id === item.agent_id)?.label : props.humans.find(user => user.id === item.user_id)?.label)
    || t(item.kind === 'agent' ? item.agent_id ? 'nativeProcesses.actorTypes.agent' : 'nativeProcesses.defaultAgent' : item.user_id ? 'nativeProcesses.actorTypes.human' : 'nativeProcesses.unassignedHuman')
}
function savedPosition(node: BpmnNode): { x: number; y: number } {
  const auto = layout.value.positions[node.id]!
  return { x: node.x > 0 ? node.x + horizontalOffset.value : auto.x,
    y: props.modelValue.actors?.length ? auto.y : node.y > 0 ? node.y : auto.y }
}
function position(node: BpmnNode): { x: number; y: number } { return drag.value?.id === node.id && drag.value.moved ? drag.value.preview : savedPosition(node) }
const dropTarget = computed(() => {
  const current = drag.value
  if (!current) return null
  const node = props.modelValue.nodes.find(node => node.id === current.id)
  if (!node) return null
  if (current.outside && (node.kind === 'task' || node.kind === 'human_task')) return { lane: null, allowed: true, create: true }
  if (!props.modelValue.actors?.length) return { lane: '', allowed: true, create: false }
  const lane = layout.value.lanes[Math.floor((current.preview.y + 44) / layout.value.laneHeight)]
  if (lane === undefined) return { lane: null, allowed: false, create: false }
  const required = node.kind === 'task' ? 'agent' : node.kind === 'human_task' ? 'human' : null
  if (props.modelValue.schema_version === 'galaris.bpmn/v2' && ['task', 'human_task', 'code', 'if'].includes(node.kind)) return { lane, allowed: true, create: false }
  return { lane, allowed: required ? lane === '' ? required === 'agent' : actor(lane)?.kind === required : lane === String(node.config.actor ?? ''), create: false }
})
const contentWidth = computed(() => Math.max(laneHeaderWidth, ...props.modelValue.nodes.map(node => savedPosition(node).x + nodeWidth(node) + 48)))
const width = computed(() => Math.max(contentWidth.value, viewportWidth.value / zoom.value))
const tableHeight = computed(() => layout.value.lanes.length * layout.value.laneHeight)
const height = tableHeight
function endpoint(id: string): { x: number; y: number; width: number } {
  const node = props.modelValue.nodes.find(item => item.id === id)
  return node ? { ...position(node), width: nodeWidth(node) } : { x: 0, y: 0, width: 0 }
}
function title(id: string): string { const node = props.modelValue.nodes.find(node => node.id === id); return node?.title || t('nativeProcesses.kinds.' + (node?.kind ?? 'task')) }
function flowPath(flow: BpmnFlow): string {
  const a = endpoint(flow.source), b = endpoint(flow.target), start = a.x + a.width, end = b.x, y1 = a.y + (props.modelValue.nodes.find(node => node.id === flow.source)?.kind === 'if' ? flow.condition === null ? 60 : 28 : 44), y2 = b.y + 44
  if (Math.abs(y1 - y2) < 1 && end > start) return `M${start} ${y1} H${end - 3}`
  const mid = end > start + 48 ? (start + end) / 2 : start + 36
  return `M${start} ${y1} H${mid - 8} Q${mid} ${y1} ${mid} ${y1 + (y2 > y1 ? 8 : -8)} V${y2 + (y2 > y1 ? -8 : 8)} Q${mid} ${y2} ${mid + (end > mid ? 8 : -8)} ${y2} H${end - 3}`
}
function flowMidpoint(flow: BpmnFlow): { x: number; y: number } { const a = endpoint(flow.source), b = endpoint(flow.target); return { x: (a.x + a.width + b.x) / 2, y: (a.y + b.y) / 2 + (props.modelValue.nodes.find(node => node.id === flow.source)?.kind === 'if' ? flow.condition === null ? 34 : 18 : 26) } }
function ports(node: BpmnNode): { side: 'input' | 'output'; outcome?: boolean }[] {
  return node.kind === 'start' ? [{ side: 'output' }] : node.kind === 'end' ? [{ side: 'input' }] : node.kind === 'if' ? [{ side: 'input' }, { side: 'output', outcome: true }, { side: 'output', outcome: false }] : [{ side: 'input' }, { side: 'output' }]
}
function adjacent(id: string, side: 'input' | 'output', outcome?: boolean): BpmnFlow[] { return props.modelValue.flows.filter(flow => side === 'input' ? flow.target === id : flow.source === id && (outcome === undefined || (flow.condition !== null) === outcome)) }
function statusClass(id: string): string { return `state-${props.statuses[id] ?? 'idle'}` }
function canConnect(node: BpmnNode): boolean {
  const current = connecting.value
  return Boolean(current && canConnectActivities(props.modelValue, current.side === 'input' ? node.id : current.id, current.side === 'input' ? current.id : node.id, current.outcome))
}
const connectionPreviewPath = computed(() => {
  const current = linkDrag.value
  if (!current) return ''
  const anchor = endpoint(current.id), target = current.target ? endpoint(current.target) : null
  const fixed = { x: anchor.x + (current.side === 'output' ? anchor.width : 0), y: anchor.y + (current.outcome === undefined ? 44 : current.outcome ? 28 : 60) }
  const loose = target ? { x: target.x + (current.side === 'input' ? target.width : 0), y: target.y + 44 } : current.point
  const from = current.side === 'output' ? fixed : loose, to = current.side === 'output' ? loose : fixed
  const bend = Math.max(40, Math.abs(to.x - from.x) / 2)
  return `M${from.x} ${from.y} C${from.x + bend} ${from.y} ${to.x - bend} ${to.y} ${to.x} ${to.y}`
})
function beginLink(event: PointerEvent, id: string, side: 'input' | 'output', outcome?: boolean): void {
  if (props.readonly || event.button !== 0 || drag.value || laneDrag.value || linkDrag.value) return
  const element = event.currentTarget as HTMLElement, origin = point(event)
  element.focus({ preventScroll: true })
  linkDrag.value = { id, side, outcome, element, pointer: event.pointerId, origin, point: origin, target: null, moved: false }
  element.setPointerCapture(event.pointerId)
}
function moveLink(event: PointerEvent): void {
  const current = linkDrag.value
  if (!current || event.pointerId !== current.pointer || props.readonly) return
  const next = point(event), moved = current.moved || Math.hypot(next.x - current.origin.x, next.y - current.origin.y) * zoom.value >= 4
  if (moved) connecting.value = { id: current.id, side: current.side, outcome: current.outcome }
  const hit = document.elementFromPoint(event.clientX, event.clientY)
  const id = hit?.closest<HTMLElement>('[data-process-node]')?.dataset.processNode
  const port = hit?.closest<HTMLElement>('[data-flow-port]')?.dataset.flowPort
  const node = props.modelValue.nodes.find(node => node.id === id)
  const target = node && (!port || port !== current.side) && canConnect(node) ? node.id : null
  linkDrag.value = { ...current, point: next, moved, target }
}
function cancelLink(): void {
  const current = linkDrag.value
  linkDrag.value = null
  if (!current) return
  if (current.moved) {
    blockedPortClick = { element: current.element, until: performance.now() + 500 }
    connecting.value = null
  }
  if (current.element.hasPointerCapture(current.pointer)) current.element.releasePointerCapture(current.pointer)
}
function portClick(event: MouseEvent): void {
  if (event.detail && blockedPortClick?.element === event.currentTarget && performance.now() < blockedPortClick.until) {
    event.preventDefault(); event.stopImmediatePropagation()
    blockedPortClick = null
  }
}
function link(source: string, target: string, outcome?: boolean): void {
  const next = connectActivities(props.modelValue, source, target, outcome)
  if (!props.readonly && next !== props.modelValue) emit('update:modelValue', next)
}
function choose(id: string): void {
  const node = props.modelValue.nodes.find(node => node.id === id)!
  if (connecting.value && !props.readonly && canConnect(node)) {
    const source = connecting.value.side === 'input' ? id : connecting.value.id
    const target = connecting.value.side === 'input' ? connecting.value.id : id
    const outcome = connecting.value.outcome
    connecting.value = null
    link(source, target, outcome)
  }
  emit('select', id)
}
function arrange(): void {
  if (props.readonly) return
  const positions = graphLayout({ ...props.modelValue, nodes: props.modelValue.nodes.map(node => ({ ...node, y: 0 })) }).positions
  emit('update:modelValue', { ...props.modelValue, nodes: props.modelValue.nodes.map(node => ({ ...node, ...positions[node.id]! })) })
}
function fit(): void { zoom.value = Math.max(.2, Math.min(1, (scroll.value?.clientWidth ?? contentWidth.value) / contentWidth.value)) }
function focusNode(id: string): void {
  const node = props.modelValue.nodes.find(node => node.id === id), viewport = scroll.value
  if (!node || !viewport) return
  const p = position(node)
  viewport.scrollTo({ left: Math.max(0, (p.x + nodeWidth(node) / 2) * zoom.value - viewport.clientWidth / 2),
    top: Math.max(0, (p.y + 44) * zoom.value - viewport.clientHeight / 2) })
  viewport.scrollIntoView({ block: 'nearest' })
}
defineExpose({ focusNode })
function setFullscreen(value: boolean): void {
  if (isFullscreen.value === value) return
  cancelDrag()
  isFullscreen.value = value
  if (value) {
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  } else if (previousBodyOverflow !== null) {
    document.body.style.overflow = previousBodyOverflow
    previousBodyOverflow = null
  }
}
async function toggleFullscreen(): Promise<void> {
  if (fullscreenBusy.value || disposed) return
  fullscreenBusy.value = true
  try {
    if (isFullscreen.value) {
      if (ownsNativeFullscreen && document.fullscreenElement === document.documentElement) await document.exitFullscreen().catch(() => {})
      ownsNativeFullscreen = false
      setFullscreen(false)
    } else {
      if (document.fullscreenEnabled && document.fullscreenElement === null) {
        try {
          await document.documentElement.requestFullscreen({ navigationUI: 'hide' })
          ownsNativeFullscreen = true
        } catch { /* Keep the viewport-sized fallback. */ }
      }
      if (disposed) {
        if (ownsNativeFullscreen && document.fullscreenElement === document.documentElement) await document.exitFullscreen().catch(() => {})
        return
      }
      setFullscreen(true)
    }
  } finally { fullscreenBusy.value = false }
}
function onFullscreenChange(): void {
  if (document.fullscreenElement === null) { ownsNativeFullscreen = false; setFullscreen(false) }
}
function onFullscreenKey(event: KeyboardEvent): void {
  if (event.key === 'Escape' && isFullscreen.value && document.fullscreenElement === null) setFullscreen(false)
}
function add(anchor: string, side: 'input' | 'output', kind: NodeKind, branch = false, outcome?: boolean): void {
  if (props.readonly) return
  const next = insertActivity(props.modelValue, anchor, side, kind, branch, outcome)
  const positions = graphLayout(next.graph).positions
  emit('update:modelValue', { ...next.graph, nodes: next.graph.nodes.map(node => ({ ...node, ...positions[node.id]! })) }); emit('select', next.id)
}
function point(event: PointerEvent): { x: number; y: number } {
  const bounds = scroll.value?.getBoundingClientRect()
  return bounds ? { x: (event.clientX - bounds.left + scroll.value!.scrollLeft) / zoom.value, y: (event.clientY - bounds.top + scroll.value!.scrollTop) / zoom.value } : { x: 0, y: 0 }
}
function begin(event: PointerEvent, id: string): void {
  if (props.readonly || connecting.value || linkDrag.value || drag.value || laneDrag.value || event.button !== 0) return
  emit('select', id)
  const p = point(event), n = endpoint(id), element = event.currentTarget as HTMLElement
  dropError.value = false
  drag.value = { id, dx: p.x - n.x, dy: p.y - n.y, pointer: event.pointerId, element, origin: p, preview: n, moved: false, outside: false }; element.setPointerCapture(event.pointerId)
}
function move(event: PointerEvent): void {
  if (linkDrag.value) { moveLink(event); return }
  const lane = laneDrag.value
  if (lane) {
    if (props.readonly || event.pointerId !== lane.pointer) return
    const viewport = scroll.value, bounds = viewport?.getBoundingClientRect()
    if (viewport && bounds && Math.abs(event.clientY - lane.originY) >= 4) {
      if (event.clientY < bounds.top + 24) viewport.scrollTop -= 16
      else if (event.clientY > bounds.bottom - 24) viewport.scrollTop += 16
    }
    laneDrag.value = { ...lane, moved: lane.moved || Math.abs(event.clientY - lane.originY) >= 4,
      target: Math.max(0, Math.min((props.modelValue.actors?.length ?? 1) - 1, Math.floor(point(event).y / layout.value.laneHeight) - 1)) }
    return
  }
  const current = drag.value
  if (!current || props.readonly || event.pointerId !== current.pointer) return
  const p = point(event)
  const bounds = scroll.value?.getBoundingClientRect()
  const centerY = p.y - current.dy + 44
  const outsideViewport = Boolean(bounds && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom))
  drag.value = { ...current, moved: current.moved || Math.hypot(p.x - current.origin.x, p.y - current.origin.y) * zoom.value >= 4,
    outside: outsideViewport || p.x < 0 || p.x > width.value || centerY < 0 || centerY >= tableHeight.value,
    preview: { x: Math.max(laneHeaderWidth + 44, Math.round((p.x - current.dx) / 16) * 16), y: Math.max(0, Math.round((p.y - current.dy) / 16) * 16) } }
}
function cancelDrag(): void {
  cancelLink()
  cancelLaneDrag()
  const current = drag.value
  drag.value = null
  if (current?.element.hasPointerCapture(current.pointer)) current.element.releasePointerCapture(current.pointer)
}
function stop(event: PointerEvent): void {
  if (linkDrag.value) {
    if (event.pointerId !== linkDrag.value.pointer) return
    moveLink(event)
    const current = linkDrag.value
    cancelLink()
    if (current.moved && current.target) link(current.side === 'output' ? current.id : current.target, current.side === 'output' ? current.target : current.id, current.outcome)
    return
  }
  if (laneDrag.value) {
    if (event.pointerId !== laneDrag.value.pointer) return
    move(event)
    const current = laneDrag.value
    const actors = orderedActors(current.id, current.target)
    cancelLaneDrag()
    if (!props.readonly && current.moved && actors.some((actor, index) => actor.id !== props.modelValue.actors?.[index]?.id)) {
      emit('update:modelValue', { ...props.modelValue, actors })
    }
    return
  }
  if (!drag.value || event.pointerId !== drag.value.pointer) return
  move(event)
  const current = drag.value, target = dropTarget.value
  if (!props.readonly && current.moved && target?.allowed) {
    let created: ProcessActor | null = null
    if (target.create) {
      created = makeActor(props.modelValue.nodes.find(node => node.id === current.id)?.kind === 'human_task' ? 'human' : 'agent')
    }
    const actorKey = created?.id ?? target.lane
    const next: BpmnGraph = { ...props.modelValue, ...(created ? { actors: [...(props.modelValue.actors ?? []), created] } : {}), nodes: props.modelValue.nodes.map(node => {
      const p = savedPosition(node)
      if (node.id !== current.id) return { ...node, ...p }
      const task = ['task', 'human_task', 'code', 'if'].includes(node.kind)
      const assigned = task && (created || props.modelValue.actors?.length) ? assignActivityActor(node, actorKey || '', { ...props.modelValue, actors: created ? [...(props.modelValue.actors ?? []), created] : props.modelValue.actors }) : node
      return { ...assigned, x: current.preview.x, y: Math.max(32, current.preview.y) }
    }) }
    cancelDrag()
    emit('update:modelValue', next)
  } else { dropError.value = !props.readonly && current.moved && !target?.allowed; cancelDrag() }
}
function key(event: KeyboardEvent, id: string): void {
  if (event.key === 'Escape') { connecting.value = null; cancelDrag(); return }
  if (props.readonly) return
  const node = props.modelValue.nodes.find(node => node.id === id)
  if (event.key === 'Delete' && node?.kind !== 'start' && (node?.kind !== 'end' || props.modelValue.nodes.filter(node => node.kind === 'end').length > 1)) { event.preventDefault(); emit('remove', id); return }
  const delta = { ArrowLeft: [-16, 0], ArrowRight: [16, 0], ArrowUp: [0, -16], ArrowDown: [0, 16] }[event.key]
  if (!delta) return
  event.preventDefault()
  emit('update:modelValue', { ...props.modelValue, nodes: props.modelValue.nodes.map(node => {
    const p = position(node)
    return { ...node, x: Math.max(laneHeaderWidth + 44, p.x + (node.id === id ? delta[0]! : 0)), y: Math.max(32, p.y + (node.id === id ? delta[1]! : 0)) }
  }) })
}
watch([() => props.modelValue, () => props.readonly], cancelDrag)
onMounted(() => {
  if (scroll.value) {
    let fitted = false
    const resize = () => {
      viewportWidth.value = scroll.value?.clientWidth ?? 0
      if (props.autoFit && !fitted && viewportWidth.value > 0) { fit(); fitted = true }
    }
    resize()
    viewportObserver = new ResizeObserver(resize)
    viewportObserver.observe(scroll.value)
  }
  document.addEventListener('fullscreenchange', onFullscreenChange)
  window.addEventListener('keydown', onFullscreenKey)
})
onBeforeUnmount(() => {
  disposed = true
  viewportObserver?.disconnect()
  cancelDrag()
  setFullscreen(false)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  window.removeEventListener('keydown', onFullscreenKey)
  if (ownsNativeFullscreen && document.fullscreenElement === document.documentElement) void document.exitFullscreen().catch(() => {})
})
</script>

<style scoped>
/* The drawing keeps the reference SVG's paper palette in either application theme. */
.diagram-editor, .drag-preview {
  --diagram-surface: #FFFFFF;
  --diagram-text: #0F172A;
  --diagram-muted: #64748B;
  --diagram-line: #475569;
  --diagram-separator: #E2E8F0;
  --diagram-lane: #FBFCFD;
  --diagram-lane-alt: #F6F8FB;
  --diagram-lane-system: #EEF3F8;
  --diagram-actor: #334155;
  --diagram-actor-alt: #3F4B5E;
  --diagram-actor-system: #1E293B;
  --diagram-actor-text: #FFFFFF;
  --diagram-actor-muted: #CBD5E1;
  --diagram-gray-fill: #F1F5F9;
  --diagram-gray-border: #94A3B8;
  --diagram-yellow-fill: #FEF3C7;
  --diagram-yellow-border: #D97706;
  --diagram-green-fill: #DDF3EF;
  --diagram-green-border: #0F766E;
  --diagram-blue-fill: #DBEAFE;
  --diagram-blue-border: #1D4ED8;
  --diagram-red-fill: #FEE2E2;
  --diagram-red-border: #B91C1C;
  --diagram-badge-yellow-text: #9A3412;
  color: var(--diagram-text);
  font-family: 'Segoe UI', system-ui, -apple-system, Helvetica, Arial, sans-serif;
}
.diagram-editor { border: 1px solid var(--diagram-separator); border-radius: 10px; overflow: hidden; background: var(--diagram-surface); }
.diagram-toolbar { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; align-items: center; padding: 12px 16px; border-bottom: 1px solid var(--q-separator-color, rgba(128, 128, 128, .24)); }
.diagram-guide { display: flex; gap: 8px; align-items: center; font-size: 12px; opacity: .75; }
.diagram-editor.fullscreen { position: fixed; z-index: 5999; inset: 0; width: 100vw; height: 100dvh; display: flex; flex-direction: column; border: 0; border-radius: 0; }
.diagram-editor.fullscreen .bpmn-scroll { flex: 0 1 auto; min-height: 0; max-height: none; }
.bpmn-scroll { overflow: auto; max-height: 72vh; }
.diagram-scale { position: relative; overflow: hidden; }
.diagram-board { position: absolute; inset: 0 auto auto 0; transform-origin: top left; }
.swimlane { position: absolute; border-bottom: 1px solid var(--diagram-separator); background: var(--diagram-lane); pointer-events: none; }
.swimlane:nth-child(even) { --diagram-actor: var(--diagram-actor-alt); background: var(--diagram-lane-alt); }
.swimlane:first-child { --diagram-actor: var(--diagram-actor-system); background: var(--diagram-lane-system); }
.swimlane.drop-allowed { outline: 2px solid var(--solaire-green-accent); outline-offset: -2px; }
.swimlane.drop-forbidden { outline: 2px dashed var(--solaire-red-accent); outline-offset: -2px; }
.new-actor-zone { --hatch-color: var(--diagram-gray-fill); height: 40px; flex-shrink: 0; display: flex; align-items: center; background-color: var(--diagram-surface); background-image: repeating-linear-gradient(135deg, transparent 0 10px, var(--hatch-color) 10px 20px); }
.new-actor-zone.active { outline: 2px solid var(--solaire-green-accent); outline-offset: -2px; }
.flow-surface { position: absolute; inset: 0; pointer-events: none; }
.flow-line { stroke: var(--diagram-line); stroke-width: 1.8; fill: none; }
.connection-preview { stroke: var(--solaire-blue-accent); stroke-width: 2; stroke-dasharray: 6 4; }
marker path { fill: var(--diagram-line); }
.flow-selected .flow-line { stroke: var(--solaire-blue-accent); stroke-width: 2.5; }
.flow-label { position: absolute; transform: translate(-50%, -50%); max-width: 150px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; font: inherit; font-size: 12px; border: 0; padding: 2px 8px; border-radius: 5px; background: var(--diagram-surface); color: var(--diagram-line); opacity: 0; cursor: pointer; }
.flow-label:hover, .flow-label:focus-visible, .flow-label.conditional, .flow-label.selected { opacity: 1; }
.node-wrap { position: absolute; height: 88px; --node-accent: var(--diagram-green-border); --node-fill: var(--diagram-green-fill); --node-border-width: 2.2px; }
.node-wrap.dragging { opacity: 0; }
.drag-preview { position: fixed; z-index: 7000; pointer-events: none; transform-origin: top left; }
.drag-preview .node-card { cursor: grabbing; }
.node-wrap.invalid-drop .node-card { cursor: not-allowed; outline-color: var(--solaire-red-accent); }
.node-card { height: 88px; width: 100%; border: var(--node-border-width) solid var(--node-accent); border-radius: 10px; display: flex; padding: 12px 20px; align-items: center; justify-content: center; background: var(--node-fill); color: var(--diagram-text); text-align: center; cursor: grab; font: inherit; touch-action: none; }
.node-card:active { cursor: grabbing; }
.readonly .node-card, .readonly .node-card:active { cursor: pointer; }
.node-card:hover { border-color: var(--node-accent); }
.node-card:focus-visible, .node-card.connect-target { outline: 2px solid var(--node-accent); outline-offset: -2px; }
.node-symbol { color: var(--node-accent); flex-shrink: 0; }
.node-wrap:not(.start):not(.end):not(.if):not(.parallel) .node-symbol { position: absolute; top: 7px; left: 7px; opacity: .7; }
.node-copy { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.node-kind { font-size: 12.5px; color: var(--diagram-line); }
.node-copy strong { font-size: 15px; font-weight: 700; line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.task { --node-accent: var(--diagram-gray-border); --node-fill: var(--diagram-gray-fill); --node-border-width: 1.5px; }
.human_task, .for, .while, .if, .parallel { --node-accent: var(--diagram-yellow-border); --node-fill: var(--diagram-yellow-fill); --node-border-width: 2px; }
.start { --node-accent: var(--diagram-blue-border); --node-fill: var(--diagram-blue-fill); }
.end { --node-accent: var(--diagram-red-border); --node-fill: var(--diagram-red-fill); }
.start .node-card, .end .node-card { height: 64px; width: 64px; margin: 12px 4px; border-radius: 50%; border: 2px solid var(--node-accent); padding: 0; justify-content: center; }
.if .node-card, .parallel .node-card { width: 58px; height: 58px; margin: 15px; border: var(--node-border-width) solid var(--node-accent); border-radius: 0; transform: rotate(45deg); padding: 0; justify-content: center; }
.if .node-symbol, .parallel .node-symbol { transform: rotate(-45deg); }
.event-title { position: absolute; top: 84px; left: 50%; transform: translateX(-50%); width: 180px; text-align: center; font-size: 12px; line-height: 16px; font-weight: 600; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.port { position: absolute; top: 44px; transform: translateY(-50%); width: 24px; height: 24px; border: 0; border-radius: 50%; background: transparent; color: var(--node-accent); cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0; touch-action: none; }
.port::before { content: ''; width: 10px; height: 10px; box-sizing: border-box; border: 1.5px solid currentColor; border-radius: 50%; background: var(--diagram-surface); }
.port.input { left: -12px; }
.port.output { right: -12px; }
.port.output-true { top: 28px; }
.port.output-false { top: 60px; }
.port-outcome { position: absolute; left: 22px; padding: 0 3px; font-size: 11px; color: var(--diagram-text); background: var(--diagram-surface); }
.port:hover::before, .port:focus-visible::before { background: currentColor; }
.port:focus-visible { outline: 2px solid var(--node-accent); outline-offset: 1px; }
.body-indicator { position: absolute; right: 8px; bottom: 6px; opacity: .55; }
.overlay { font-size: 10px; position: absolute; top: 118px; width: 220px; left: 50%; transform: translateX(-50%); text-align: center; }
.node-badge { position: absolute; top: -10px; right: 4px; z-index: 1; min-height: 20px; padding: 2px 7px; border: 1.2px solid var(--status-accent, var(--diagram-gray-border)); border-radius: 10px; background: var(--status-fill, var(--diagram-gray-fill)); color: var(--status-text, var(--diagram-line)); font-size: 10.5px; font-weight: 700; line-height: 14px; white-space: nowrap; pointer-events: none; }
.state-success, .state-completed { --status-accent: var(--diagram-green-border); --status-fill: var(--diagram-green-fill); --status-text: var(--diagram-green-border); }
.state-error, .state-failed { --status-accent: var(--diagram-red-border); --status-fill: var(--diagram-red-fill); --status-text: var(--diagram-red-border); }
.state-waiting, .state-running { --status-accent: var(--diagram-yellow-border); --status-fill: var(--diagram-yellow-fill); --status-text: var(--diagram-badge-yellow-text); }
.state-running { --status-accent: var(--solaire-blue-accent); --status-fill: var(--solaire-blue-light); --status-text: var(--diagram-text); }
.state-waiting { --status-accent: var(--solaire-yellow-accent); --status-fill: var(--solaire-yellow-light); --status-text: var(--diagram-text); }
.state-running .node-card, .state-waiting .node-card { background: var(--status-fill); border-color: var(--status-accent); outline: 3px solid var(--status-accent); outline-offset: 4px; }
:global(body.body--dark) .state-running { --status-fill: var(--solaire-blue-dark); }
:global(body.body--dark) .state-waiting { --status-fill: var(--solaire-yellow-dark); }
.connect-hint { display: flex; gap: 8px; align-items: center; padding: 8px 16px; background: var(--diagram-gray-fill); font-size: 13px; }
.drop-message { display: flex; gap: 8px; align-items: center; padding: 10px 16px; font-size: 13px; }
:global(.handle-menu) { background: #fff; color: #292C30; border: 1px solid rgba(128, 128, 128, .24); border-radius: 12px; }
:global(.body--dark .handle-menu) { background: #101010; color: #EEEEF0; }
:global(.process-context-form) { width: min(480px, calc(100vw - 24px)); border: 1px solid var(--q-separator-color, rgba(128, 128, 128, .24)); border-radius: 10px; }
:global(.process-activity-form) { width: min(640px, calc(100vw - 24px)); }
@media (max-width: 1023px) { .diagram-toolbar { padding: 10px; } .diagram-guide { max-width: 280px; } }
</style>
