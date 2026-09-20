<template>
    <q-card flat bordered class="memory-item-card">
        <q-card-section v-if="loading" class="q-pa-sm">
            <q-skeleton type="text" width="55%" />
            <q-skeleton type="text" width="80%" />
        </q-card-section>

        <q-card-section v-else-if="unavailable && !preview" class="memory-unavailable q-pa-sm">
            <q-icon name="visibility_off" color="grey-6" size="sm" />
            <span class="text-body2 text-grey-7">{{ t('task.memory.itemUnavailable') }}</span>
        </q-card-section>

        <template v-else-if="displayedItem">
            <q-card-section class="memory-title text-subtitle2 text-weight-medium q-py-xs q-px-sm">
                <q-badge v-if="displayedItem.nodeKind === 'document'" class="memory-kind-badge q-mr-sm"
                    :title="t('task.memory.documentKindHint')">
                    {{ t('memory.graph.roles.document') }}
                </q-badge>
                <q-badge v-if="displayedItem.memoryType" class="memory-type-badge q-mr-sm"
                    :title="t(`task.memory.typeHints.${displayedItem.memoryType}`)">
                    {{ t(`memory.types.${displayedItem.memoryType}`) }}
                </q-badge>
                <DocumentIcon v-if="displayedItem.nodeKind === 'document' && documentId" :document-id="documentId" :title="displayedItem.title" class="q-mr-sm" />{{ displayedItem.title }}
            </q-card-section>

            <q-separator />

            <q-card-section v-if="displayedItem.nodeKind === 'document'" class="q-pa-sm">
                <div class="row items-center q-gutter-sm">
                    <q-btn flat dense no-caps color="primary" icon="visibility"
                        :label="t('task.memory.viewDocument')" :disable="!documentId || agentId == null"
                        @click="documentOpen = true" />
                    <q-space />
                    <q-badge v-if="documentId" outline color="primary" class="memory-document-url cursor-pointer"
                        role="button" tabindex="0" :aria-label="t('documents.copyUrl')"
                        @click="copyDocumentUrl" @keydown.enter.prevent="copyDocumentUrl" @keydown.space.prevent="copyDocumentUrl">
                        <span>{{ `document://${documentId}` }}</span>
                        <q-tooltip>{{ t('documents.copyUrl') }}</q-tooltip>
                    </q-badge>
                </div>
            </q-card-section>
            <q-card-section v-else class="q-pa-sm">
                <div v-if="displayedItem.content" class="memory-content text-body2">
                    <EditorialContent v-if="isMarkdown || item?.media_type === 'text/html'" :content="displayedItem.content" :media-type="item?.media_type" />
                    <div v-else class="memory-plain-text">{{ displayedItem.content }}</div>
                </div>
                <div v-else class="text-caption text-grey-7">
                    {{ t('task.memory.contentUnavailable') }}
                </div>
            </q-card-section>
        </template>
    </q-card>

    <q-dialog v-if="documentOpen && documentId && agentId != null" v-model="documentOpen" allow-focus-outside :maximized="$q.screen.lt.md" @before-hide="flushDocument">
        <q-card class="memory-document-dialog galaris-detail-dialog column no-wrap">
            <q-card-section class="galaris-dialog-title row items-center no-wrap">
                <DocumentIcon :document-id="documentId" :title="displayedItem?.title ?? ''" size="24px" class="q-mr-sm" />
                <div class="text-h6 ellipsis">{{ displayedItem?.title }}</div>
                <q-space />
                <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
            </q-card-section>
            <div class="memory-document-reader">
                <WorkingDocumentEditor ref="documentEditor" :document-id="documentId" :agent-id="agentId"
                    content-min-height="min(42vh, 440px)" content-max-height="52vh" />
            </div>
        </q-card>
    </q-dialog>
</template>

<script lang="ts">
import type { MemoryNodeKind, MemoryType } from '@/app/memory/types'

export interface MemoryItemPreview {
    id?: string
    title: string
    content: string
    memoryType?: MemoryType
    nodeKind?: MemoryNodeKind
    keywords: string[]
}
</script>

<script setup lang="ts">
import { WorkingDocumentIcon as DocumentIcon } from '@/core/util'
import { computed, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { copyToClipboard, useQuasar } from 'quasar'
import type { MemoryItemDetail } from '@/app/memory/types'
import { EditorialContent, WorkingDocumentEditor } from '@/core/util'

const props = withDefaults(defineProps<{
    agentId?: number | null
    item?: MemoryItemDetail
    preview?: MemoryItemPreview
    loading?: boolean
    unavailable?: boolean
}>(), {
    agentId: null,
    item: undefined,
    preview: undefined,
    loading: false,
    unavailable: false,
})

const { t } = useI18n()
const $q = useQuasar()
const documentOpen = ref(false)
const documentEditor = useTemplateRef<InstanceType<typeof WorkingDocumentEditor>>('documentEditor')

function flushDocument(): void {
    void documentEditor.value?.flush()
}

const displayedItem = computed<MemoryItemPreview | null>(() => {
    if (props.item) {
        return {
            id: props.item.id,
            title: props.item.title,
            content: props.item.payload.text || '',
            memoryType: props.item.memory_type,
            nodeKind: props.item.node_kind,
            keywords: props.item.keywords,
        }
    }
    return props.preview || null
})

const documentId = computed(() => displayedItem.value?.nodeKind === 'document' ? displayedItem.value.id : undefined)
watch([documentId, () => props.agentId], () => { documentOpen.value = false })

async function copyDocumentUrl(): Promise<void> {
    if (!documentId.value) return
    try {
        await copyToClipboard(`document://${documentId.value}`)
        $q.notify({ type: 'positive', message: t('documents.urlCopied'), timeout: 1600 })
    } catch {
        $q.notify({ type: 'negative', message: t('documents.urlCopyError') })
    }
}

const isMarkdown = computed(() => {
    if (!props.item) return false
    return props.item.media_type === 'text/markdown'
        || props.item.content_type === 'text/markdown'
        || props.item.filename?.toLowerCase().endsWith('.md') === true
})
</script>

<style scoped>
.memory-item-card {
    min-width: 0;
    border-radius: 4px;
}

.memory-title {
    overflow-wrap: anywhere;
    background: var(--solaire-gray-light);
}

.memory-kind-badge {
    color: inherit;
    border: 1px solid var(--solaire-blue-accent);
    background: var(--solaire-blue-light);
}

.memory-type-badge {
    color: inherit;
    border: 1px solid var(--solaire-iris-accent);
    background: var(--solaire-iris-light);
}

.memory-content {
    overflow-wrap: anywhere;
}

.memory-content :deep(.rich-content) {
    background-color: transparent;
}

.memory-plain-text {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

.memory-document-url {
    min-width: 0;
    max-width: 100%;
    overflow-wrap: anywhere;
    white-space: normal;
    text-align: left;
}

.memory-document-dialog {
    width: min(94vw, 980px);
    max-width: 980px;
    max-height: calc(100dvh - 32px);
}

.memory-document-reader {
    min-height: 0;
    overflow-y: auto;
}

.memory-unavailable {
    display: flex;
    align-items: center;
    gap: 8px;
}

body.body--dark .memory-title {
    background: var(--solaire-gray-dark);
}

body.body--dark .memory-kind-badge {
    background: var(--solaire-blue-dark);
}

body.body--dark .memory-type-badge {
    background: var(--solaire-iris-dark);
}

body.body--dark .memory-item-card :deep(.text-grey-7) {
    color: #b0bec5 !important;
}
</style>
