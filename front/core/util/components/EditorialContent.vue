<template>
  <RichText v-if="mediaType === 'text/html'" :content="content" :profile="profile" :resolve-image="resolveImage" />
  <Markdown v-else-if="mediaType === 'text/markdown'" :content="content" />
  <div v-else class="editorial-plain">{{ content }}</div>
</template>
<script setup lang="ts">
import RichText from './RichText.vue'
import Markdown from './Markdown.vue'
import type { ContentProfile } from '../richText'
const { content, mediaType = 'text/html', profile = 'rich-text', resolveImage } = defineProps<{
  content: string; mediaType?: string; profile?: ContentProfile
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>
}>()
</script>
<style scoped>.editorial-plain { white-space: pre-wrap; }</style>
