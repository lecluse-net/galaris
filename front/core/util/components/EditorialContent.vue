<template>
  <RichText v-if="mediaType === 'text/html'" :content="content" :profile="profile" :resource-agent-id="resourceAgentId" :resolve-image="resolveImage" :resolve-resource-image="resolveResourceImage" :register-reference-actions="registerReferenceActions" :resize-reference="resizeReference" />
  <Markdown v-else-if="mediaType === 'text/markdown'" :content="content" />
  <div v-else class="editorial-plain">{{ content }}</div>
</template>
<script setup lang="ts">
import RichText from './RichText.vue'
import Markdown from './Markdown.vue'
import type { ContentProfile } from '../richText'
import type { ResourceImageResolver } from '../resourceCards'
import type { DocumentEmbedSize, DocumentReferenceAction } from '../documentReference'
const { content, mediaType = 'text/html', profile = 'rich-text', resolveImage, resolveResourceImage, resourceAgentId, registerReferenceActions, resizeReference } = defineProps<{
  content: string; mediaType?: string; profile?: ContentProfile
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>
  resolveResourceImage?: ResourceImageResolver
  resourceAgentId?: number | null
  registerReferenceActions?: (card: HTMLElement, actions: readonly DocumentReferenceAction[]) => void
  resizeReference?: (index: number, uri: string, size: DocumentEmbedSize) => void
}>()
</script>
<style scoped>.editorial-plain { white-space: pre-wrap; }</style>
