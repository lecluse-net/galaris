<template>
  <section class="execution-trace" :class="{ 'execution-trace--error': error, 'execution-trace--warning': warning }">
    <div class="trace-header" :class="{ 'trace-header--compact': compact }">
      <component
        :is="expandable ? 'button' : 'div'" :type="expandable ? 'button' : undefined" class="trace-summary"
        :aria-label="expandable ? label || t('chat.thinking') : undefined"
        :aria-description="compact && hasHiddenTools ? t('chat.deep.previousActions') : undefined"
        :aria-expanded="expandable ? expanded : undefined" @click="toggle"
      >
        <q-icon :name="icon" class="summary-icon" :class="{ 'gt-sm': !label }" />
        <span class="summary-label" :class="{ 'gt-sm': !label }">{{ label || t('chat.thinking') }}</span>
        <q-spinner-dots v-if="running" color="primary" size="22px" />
        <slot name="status" />
        <span v-if="toolSummaries.length" class="summary-tools">
          <span v-if="compact" class="summary-overflow" :class="{ 'summary-overflow--visible': hasHiddenTools }"
            :title="t('chat.deep.previousActions')" aria-hidden="true">…</span>
          <span class="summary-tools-viewport">
            <span ref="toolList" class="summary-tool-list">
              <span
                v-for="(tool, index) in toolSummaries" :key="`${tool.name}:${index}`"
                class="tool-summary" :class="`tool-summary--${tool.tone}`"
              >
                <q-icon :name="tool.icon" />
                <span>{{ tool.name }}</span>
              </span>
            </span>
          </span>
        </span>
        <span v-if="expandable || executionTime !== undefined || (cost && cost > 0)" class="summary-tail">
          <span v-if="executionTime !== undefined || (cost && cost > 0)" class="summary-metrics">
            <span v-if="executionTime !== undefined">{{ formatDuration(executionTime) }}</span>
            <span v-if="cost && cost > 0">{{ formatCost(cost) }}</span>
          </span>
          <q-icon v-if="expandable" :name="expanded ? 'expand_less' : 'expand_more'" aria-hidden="true" />
        </span>
      </component>
      <div v-if="$slots.controls" class="trace-controls"><slot name="controls" /></div>
    </div>
    <slot name="notice" />
    <q-slide-transition>
      <div v-if="expandable && detailsOpened" v-show="expanded" class="trace-detail">
        <slot />
      </div>
    </q-slide-transition>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = withDefaults(defineProps<{
  label: string
  icon: string
  tools: readonly string[]
  running?: boolean
  error?: boolean
  warning?: boolean
  executionTime?: number
  cost?: number
  expandable?: boolean
  recentTools?: readonly string[]
}>(), { expandable: true })
const expanded = defineModel<boolean>('expanded', { default: false })
const emit = defineEmits<{ open: [] }>()
const { t } = useI18n()
const detailsOpened = ref(false)

function toggle(): void {
  if (!props.expandable) return
  expanded.value = !expanded.value
  if (expanded.value) {
    detailsOpened.value = true
    emit('open')
  }
}

type ToolTone = 'web' | 'file' | 'task' | 'message' | 'media' | 'code' | 'calendar' | 'data' | 'default'
interface ToolSummary { name: string; icon: string; tone: ToolTone }

const compact = computed(() => props.recentTools !== undefined && !expanded.value)
const toolSummaries = computed(() => {
  const tools = compact.value && props.recentTools ? [...props.recentTools].reverse() : props.tools
  return tools.filter(name => name.toLowerCase() !== 'thinking').map(name => ({ name, ...toolPresentation(name) }))
})
const toolList = useTemplateRef<HTMLSpanElement>('toolList')
const hasHiddenTools = ref(false)

watch([compact, toolList], ([isCompact, list], _previous, onCleanup) => {
  hasHiddenTools.value = false
  const viewport = list?.parentElement
  if (!isCompact || !list || !viewport) return
  const update = () => {
    hasHiddenTools.value = list.offsetHeight > viewport.clientHeight
  }
  const observer = new ResizeObserver(update)
  observer.observe(list)
  onCleanup(() => observer.disconnect())
  update()
}, { flush: 'post' })

function toolPresentation(name: string): Pick<ToolSummary, 'icon' | 'tone'> {
  const normalized = name.toLowerCase()
  if (/(search|web|browser|url|http)/.test(normalized)) return { icon: 'travel_explore', tone: 'web' }
  if (/(file|document|memory|workspace)/.test(normalized)) return { icon: 'description', tone: 'file' }
  if (/(task|process|workflow|goal)/.test(normalized)) return { icon: 'account_tree', tone: 'task' }
  if (/(message|messenger|chat|mail|telegram|whatsapp|matrix)/.test(normalized)) return { icon: 'forum', tone: 'message' }
  if (/(image|photo|video|audio|voice|speech)/.test(normalized)) return { icon: 'perm_media', tone: 'media' }
  if (/(code|shell|exec|command|terminal)/.test(normalized)) return { icon: 'terminal', tone: 'code' }
  if (/(calendar|(^|[_:. -])(event|date|time)([_:. -]|$))/.test(normalized)) return { icon: 'event', tone: 'calendar' }
  if (/(database|query|sql|(^|[_:. -])data([_:. -]|$))/.test(normalized)) return { icon: 'storage', tone: 'data' }
  return { icon: 'build_circle', tone: 'default' }
}
function formatDuration(seconds: number): string { return seconds < 1 ? `${Math.round(seconds * 1_000)} ms` : `${seconds.toFixed(1)} s` }
function formatCost(cost: number): string { return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', maximumFractionDigits: 4 }).format(cost) }

</script>

<style scoped>
.execution-trace { margin: 2px -9px 8px; overflow: hidden; color: var(--chat-text-secondary, #536071); background: var(--chat-surface-soft, #f5f7fa); border: 1px solid var(--chat-border, rgba(53, 69, 94, .1)); border-radius: 10px; }
.execution-trace:first-child { margin-top: -6px; }
.execution-trace--error { color: var(--q-negative); background: var(--chat-danger-soft, #fff1f1); border-color: color-mix(in srgb, var(--q-negative) 34%, transparent); }
.execution-trace--warning { background: var(--solaire-orange-light); border-color: var(--solaire-orange-accent); }
.execution-trace--warning .summary-icon { color: var(--solaire-orange-accent); }
body.body--dark .execution-trace--warning { color: var(--chat-text-secondary, #EEEEF0); background: var(--solaire-orange-dark); }
.trace-summary { display: flex; width: 100%; min-height: 34px; align-items: center; flex-wrap: wrap; gap: 5px 7px; padding: 6px 9px; color: inherit; background: transparent; border: 0; font: inherit; text-align: left; }
button.trace-summary { cursor: pointer; }
.trace-header { display: flex; align-items: center; flex-wrap: wrap; }
.trace-header .trace-summary { flex: 1; width: auto; min-width: 0; }
.trace-controls { display: flex; gap: 2px; padding: 2px 6px; color: var(--solaire-blue-accent); }
.summary-icon { font-size: 18px; }
.summary-label { font-size: .75rem; font-weight: 650; }
.summary-tail { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 7px; margin-left: auto; }
.summary-metrics { display: flex; gap: 7px; color: var(--chat-text-subtle, #8a93a2); font-size: .66rem; }
.summary-tools,.summary-tools-viewport,.summary-tool-list { display: contents; }
.trace-header--compact,.trace-header--compact .trace-summary { flex-wrap: nowrap; white-space: nowrap; }
.trace-header--compact :slotted([role="status"]) { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.trace-header--compact .summary-tools { --tool-chip-height: 22px; display: flex; flex: 1 1 0; min-width: 0; align-items: center; }
.summary-overflow { flex: 0 0 1em; visibility: hidden; text-align: center; }
.summary-overflow--visible { visibility: visible; }
.trace-header--compact .summary-tools-viewport { display: block; flex: 1; min-width: 0; block-size: var(--tool-chip-height); overflow: hidden; }
/* The newest chips wrap first and read chronologically from left to right within each row. */
.trace-header--compact .summary-tool-list { display: flex; flex-flow: row-reverse wrap; justify-content: flex-end; column-gap: 7px; }
.trace-header--compact .tool-summary { flex: none; max-width: 100%; block-size: var(--tool-chip-height); }
.trace-header--compact .tool-summary > span { overflow: hidden; text-overflow: ellipsis; }
.tool-summary { display: inline-flex; min-width: 0; align-items: center; gap: 4px; padding: 3px 7px; border-radius: 999px; font-size: .67rem; }
.tool-summary--web { color: #0d5f9f; background: #e3f2fd; }
.tool-summary--file { color: #6741a5; background: #eee7fb; }
.tool-summary--task { color: #00796b; background: #dff3ef; }
.tool-summary--message { color: #3f51a5; background: #e7eafb; }
.tool-summary--media { color: #a64b00; background: #fff0df; }
.tool-summary--code { color: #37474f; background: #e4ecef; }
.tool-summary--calendar { color: #2e7d32; background: #e5f4e7; }
.tool-summary--data { color: #8a3568; background: #f7e5f0; }
.tool-summary--default { color: var(--chat-text-secondary, #4e6177); background: var(--chat-surface-raised, #e8edf4); }
.trace-detail { max-height: min(720px, 72vh); padding: 4px 8px 8px; overflow: auto; background: var(--chat-surface-raised, #fff); border-top: 1px solid var(--chat-border, rgba(53, 69, 94, .09)); }
.trace-detail :deep(.exec-expansion) { margin-top: 0; }
.trace-detail :deep(.execution-result-shell) { margin-top: 0; background: transparent; border: 0; border-radius: 0; box-shadow: none; }
.trace-detail :deep(.execution-result-shell > .q-card__section) { padding: 2px 0 0; }
.trace-detail :deep(.execution-result-shell > .q-card__section > .q-tabs) { min-height: 26px; }
.trace-detail :deep(.execution-result-shell > .q-card__section > .q-tabs .q-tab) { min-height: 26px; padding: 0 6px; }
.trace-detail :deep(.execution-result-shell > .q-card__section > .q-tabs .q-tab__label) { font-size: .62rem; line-height: 1; }
.trace-detail :deep(.execution-result-shell > .q-card__section > .q-tabs .q-icon) { font-size: 13px; }
</style>
