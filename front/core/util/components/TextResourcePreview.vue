<template>
  <article class="text-resource-preview" :class="{ 'text-resource-preview--fit': fit, 'text-resource-preview--code': !markdown }" :aria-label="title">
    <Markdown v-if="markdown" :content="content" />
    <CodeEditor
      v-else
      :model-value="content ?? ''"
      :label="title"
      :language="resourceTextLanguage(mediaType, title) ?? 'text'"
      readonly
      :show-error="false"
      fill-height
    />
  </article>
</template>

<script setup lang="ts">
import Markdown from './Markdown.vue'
import CodeEditor from './CodeEditor.vue'
import { resourceTextLanguage } from '../resourceText'

defineProps<{
  content: string | undefined
  title: string
  fit: boolean
  markdown: boolean
  mediaType: string
}>()
</script>

<style scoped>
.text-resource-preview {
  box-sizing: border-box;
  width: 960px;
  min-height: var(--galaris-preview-height, 100dvh);
  padding: 72px clamp(18px, 4vw, 56px) 68px;
  overflow-wrap: anywhere;
  color: #292c30;
  background: #fff;
}
.text-resource-preview--fit { width: 100%; }
.text-resource-preview--code { height: var(--galaris-preview-height, 100dvh); padding: 72px 16px 16px; }
.text-resource-preview :deep(img) { display: block; max-width: 100%; height: auto; }
.text-resource-preview :deep(table) { display: block; overflow-x: auto; }
body.body--dark .text-resource-preview { color: #eeeef0; background: #101010; }
</style>
