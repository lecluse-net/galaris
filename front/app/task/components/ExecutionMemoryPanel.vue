<template>
    <div class="execution-memory-panel">
        <section v-if="context" class="memory-section">
            <div v-if="context.enabled && !context.error" class="text-caption text-grey-7">
                {{ t('task.memory.selectionSummary', {
                    retrieved: context.retrievedCount,
                    injected: context.count,
                }) }}
            </div>

            <q-banner v-if="context.error" rounded class="bg-red-1 text-negative q-mt-md">
                <template #avatar><q-icon name="error_outline" /></template>
                {{ t('task.memory.errorDetail') }}
            </q-banner>

            <div v-else-if="context.enabled">
                <div v-if="context.memoryIds.length" class="memory-items q-mt-sm">
                    <MemoryItemCard
                        v-for="memoryId in context.memoryIds"
                        :key="memoryId"
                        :agent-id="agentId"
                        :item="itemsById.get(memoryId)"
                        :loading="loadingIds.has(memoryId)"
                        :unavailable="failedIds.has(memoryId)"
                    />
                </div>
                <div v-else class="memory-empty q-mt-md">
                    <q-icon name="inbox" size="md" color="blue-grey-5" />
                    <span>{{ t('task.memory.noResult') }}</span>
                </div>

            </div>
            <div v-else class="memory-empty q-mt-md">
                <q-icon name="remove_circle_outline" size="md" color="grey-5" />
                <span>{{ t('task.memory.notRequestedDetail') }}</span>
            </div>
        </section>

        <section v-if="calls.length" class="memory-section">
            <div class="q-mb-md">
                <div class="text-subtitle1 text-weight-medium">
                    {{ t('task.memory.duringExecution') }}
                </div>
                <div class="text-body2 text-grey-7">
                    {{ t('task.memory.duringExecutionHint') }}
                </div>
            </div>

            <div class="column q-gutter-md">
                <q-card
                    v-for="call in presentedCalls"
                    :key="call.index"
                    flat
                    bordered
                    class="memory-call"
                >
                    <q-card-section class="q-pb-sm">
                        <div class="row items-center justify-between q-col-gutter-sm">
                            <div class="row items-center col no-wrap">
                                <q-avatar
                                    color="blue-grey-1"
                                    text-color="blue-grey-8"
                                    :icon="call.icon"
                                    size="36px"
                                />
                                <div class="q-ml-sm">
                                    <div class="text-subtitle2">{{ call.label }}</div>
                                    <div v-if="call.query" class="text-caption text-grey-7">
                                        {{ call.query }}
                                    </div>
                                </div>
                            </div>
                            <q-chip
                                dense
                                :color="call.error ? 'red-1' : 'green-1'"
                                :text-color="call.error ? 'negative' : 'positive'"
                                :icon="call.error ? 'error_outline' : 'check_circle'"
                            >
                                {{ call.error ? t('task.memory.status.error') : t('task.memory.status.success') }}
                            </q-chip>
                        </div>
                    </q-card-section>

                    <q-separator v-if="call.memoryIds.length || call.previews.length || call.message" />

                    <q-card-section v-if="call.memoryIds.length || call.previews.length" class="q-pt-md">
                        <div class="memory-items">
                            <MemoryItemCard
                                v-for="memoryId in call.memoryIds"
                                :key="memoryId"
                                :agent-id="agentId"
                                :item="itemsById.get(memoryId)"
                                :preview="call.previewById.get(memoryId)"
                                :loading="loadingIds.has(memoryId)"
                                :unavailable="failedIds.has(memoryId)"
                            />
                            <MemoryItemCard
                                v-for="(preview, previewIndex) in call.unresolvedPreviews"
                                :key="`preview-${call.index}-${previewIndex}`"
                                :agent-id="agentId"
                                :preview="preview"
                            />
                        </div>
                    </q-card-section>
                    <q-card-section v-else-if="call.message" class="text-body2 text-grey-8 q-pt-sm">
                        {{ call.message }}
                    </q-card-section>
                </q-card>
            </div>
        </section>

        <div v-if="!context && !calls.length" class="memory-empty q-pa-lg">
            <span>{{ t('task.memory.noMemory') }}</span>
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AIMessage } from '../types'
import type { MemoryItemDetail, MemoryType, MemoryNodeKind } from '@/app/memory/types'
import { memoryService } from '@/app/memory/services/memoryService'
import MemoryItemCard, { type MemoryItemPreview } from './MemoryItemCard.vue'

interface MemoryContextTrace {
    enabled: boolean
    query: string
    count: number
    retrievedCount: number
    truncated: boolean
    memoryIds: string[]
    error: string
}

interface MemoryCall {
    message: AIMessage
    index: number
    operation: string
}

interface PresentedCall {
    index: number
    icon: string
    label: string
    query: string
    error: boolean
    message: string
    memoryIds: string[]
    previews: MemoryItemPreview[]
    previewById: Map<string, MemoryItemPreview>
    unresolvedPreviews: MemoryItemPreview[]
}

const props = defineProps<{
    agentId?: number | null
    context: MemoryContextTrace | null
    calls: MemoryCall[]
}>()

const { t } = useI18n()
const itemsById = ref<Map<string, MemoryItemDetail>>(new Map())
const loadingIds = ref<Set<string>>(new Set())
const failedIds = ref<Set<string>>(new Set())
let loadGeneration = 0

function parseResult(content: string | null | undefined): Record<string, unknown> | null {
    const value = (content || '').trim()
    if (!value) return null
    try {
        const parsed: unknown = JSON.parse(value)
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
            ? parsed as Record<string, unknown>
            : null
    } catch {
        const start = value.indexOf('{')
        const end = value.lastIndexOf('}')
        if (start < 0 || end <= start) return null
        try {
            const parsed: unknown = JSON.parse(value.slice(start, end + 1))
            return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
                ? parsed as Record<string, unknown>
                : null
        } catch {
            return null
        }
    }
}

function stringValue(value: unknown): string {
    return typeof value === 'string' ? value.trim() : ''
}

function resultMemoryIds(result: Record<string, unknown> | null): string[] {
    if (!result) return []
    const ids: string[] = []
    const directId = stringValue(result.memory_id)
    if (directId) ids.push(directId)
    if (Array.isArray(result.memories)) {
        for (const rawMemory of result.memories) {
            if (!rawMemory || typeof rawMemory !== 'object' || Array.isArray(rawMemory)) continue
            const memoryId = stringValue((rawMemory as Record<string, unknown>).memory_id)
            if (memoryId) ids.push(memoryId)
        }
    }
    return [...new Set(ids)]
}

function searchPreviews(result: Record<string, unknown> | null): MemoryItemPreview[] {
    if (!result || !Array.isArray(result.memories)) return []
    return result.memories.flatMap(rawMemory => {
        if (!rawMemory || typeof rawMemory !== 'object' || Array.isArray(rawMemory)) return []
        const memory = rawMemory as Record<string, unknown>
        const type = stringValue(memory.type)
        const nodeKind = stringValue(memory.node_kind)
        return [{
            id: stringValue(memory.memory_id) || undefined,
            title: stringValue(memory.title) || t('task.memory.untitled'),
            content: stringValue(memory.excerpt),
            memoryType: isMemoryType(type) ? type : undefined,
            nodeKind: isNodeKind(nodeKind) ? nodeKind : undefined,
            keywords: [],
        }]
    })
}

function argumentPreview(call: MemoryCall): MemoryItemPreview | null {
    if (!['memory_remember', 'memory_index'].includes(call.operation)) return null
    const args = call.message.tool_arguments || {}
    const result = parseResult(call.message.content)
    const memoryType = stringValue(args.memory_type)
    return {
        id: resultMemoryIds(result)[0],
        title: stringValue(args.title) || t('task.memory.untitled'),
        content: stringValue(args.content) || stringValue(args.text),
        memoryType: isMemoryType(memoryType) ? memoryType : undefined,
        nodeKind: 'memory',
        keywords: Array.isArray(args.keywords)
            ? args.keywords.map(stringValue).filter(Boolean)
            : Array.isArray(args.tags)
                ? args.tags.map(stringValue).filter(Boolean)
                : [],
    }
}

function isMemoryType(value: string): value is MemoryType {
    return ['core', 'working', 'episodic', 'semantic', 'procedural', 'social'].includes(value)
}

function isNodeKind(value: string): value is MemoryNodeKind {
    return value === 'memory' || value === 'document'
}

function operationLabel(operation: string): string {
    const known = ['memory_search', 'memory_get', 'memory_remember', 'memory_index', 'memory_forget', 'memory_summarize']
    return known.includes(operation)
        ? t(`task.memory.operations.${operation}`)
        : t('task.memory.operations.other')
}

function operationIcon(operation: string): string {
    return ({
        memory_search: 'manage_search',
        memory_get: 'visibility',
        memory_remember: 'add_circle_outline',
        memory_index: 'add_circle_outline',
        memory_forget: 'delete_outline',
        memory_summarize: 'summarize',
    } as Record<string, string>)[operation] || 'neurology'
}

const presentedCalls = computed<PresentedCall[]>(() => props.calls.map(call => {
    const result = parseResult(call.message.content)
    const argumentId = ['memory_get'].includes(call.operation)
        ? stringValue(call.message.tool_arguments?.memory_id)
        : ''
    const memoryIds = call.operation === 'memory_forget'
        ? []
        : [...new Set([argumentId, ...resultMemoryIds(result)].filter(Boolean))]
    const previews = searchPreviews(result)
    const createdPreview = argumentPreview(call)
    if (createdPreview) previews.push(createdPreview)
    const previewById = new Map(
        previews.filter(preview => preview.id).map(preview => [preview.id as string, preview]),
    )
    const query = call.operation === 'memory_search'
        ? stringValue(call.message.tool_arguments?.query)
        : ''
    const error = call.message.success === false || Boolean(stringValue(result?.error))
    let message = ''
    if (error) message = t('task.memory.errorDetail')
    else if (call.operation === 'memory_forget') message = t('task.memory.forgottenDuringExecution')
    else if (!memoryIds.length && !previews.length) message = t('task.memory.noReturnedContent')

    return {
        index: call.index,
        icon: operationIcon(call.operation),
        label: operationLabel(call.operation),
        query,
        error,
        message,
        memoryIds,
        previews,
        previewById,
        unresolvedPreviews: previews.filter(preview => !preview.id || !memoryIds.includes(preview.id)),
    }
}))

const referencedIds = computed(() => [...new Set([
    ...(props.context?.memoryIds || []),
    ...presentedCalls.value.flatMap(call => call.memoryIds),
])])

watch(
    [() => props.agentId, () => referencedIds.value.join('|')],
    async ([agentId]) => {
        const generation = ++loadGeneration
        itemsById.value = new Map()
        failedIds.value = new Set()
        if (typeof agentId !== 'number' || !referencedIds.value.length) {
            loadingIds.value = new Set()
            return
        }

        loadingIds.value = new Set(referencedIds.value)
        const results = await Promise.allSettled(
            referencedIds.value.map(memoryId => memoryService.getItem(memoryId, agentId)),
        )
        if (generation !== loadGeneration) return

        const loaded = new Map<string, MemoryItemDetail>()
        const failed = new Set<string>()
        results.forEach((result, index) => {
            const memoryId = referencedIds.value[index]
            if (!memoryId) return
            if (result.status === 'fulfilled') loaded.set(memoryId, result.value)
            else failed.add(memoryId)
        })
        itemsById.value = loaded
        failedIds.value = failed
        loadingIds.value = new Set()
    },
    { immediate: true },
)
</script>

<style scoped>
.execution-memory-panel {
    display: grid;
    gap: 16px;
}

.memory-section {
    min-width: 0;
}

.memory-items {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
}

.memory-call {
    border-radius: 10px;
}

.memory-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    min-height: 72px;
    color: #607d8b;
    text-align: center;
}

body.body--dark .memory-call {
    border-color: #3b474b;
    background: #242424;
}

body.body--dark .memory-empty {
    color: #b0bec5;
}

body.body--dark .execution-memory-panel :deep(.text-grey-7),
body.body--dark .execution-memory-panel :deep(.text-grey-8) {
    color: #b0bec5 !important;
}
</style>
