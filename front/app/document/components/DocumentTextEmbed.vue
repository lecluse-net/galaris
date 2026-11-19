<template>
  <div class="document-text-embed">
    <div class="document-text-embed-viewport" role="region" :aria-label="document.title" tabindex="0"
      @pointerdown.stop @keydown.stop>
      <div ref="content" class="document-text-embed-content">
        <EditorialContent :content="document.payload.text ?? ''" :media-type="document.media_type"
          profile="document" :resource-agent-id="agentId" :resolve-image="resolveImage" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useTemplateRef } from 'vue'
import { captureElementRendering, EditorialContent } from '@/core/util'
import type { DocumentDetail } from '../types'

defineProps<{ document: DocumentDetail; agentId?: number | null; resolveImage: (documentId: string, attachmentId: string) => Promise<Blob> }>()

const content = useTemplateRef('content')

async function capture(signal: AbortSignal): Promise<string> {
  if (!content.value) throw new Error('Text rendering unavailable')
  return captureElementRendering(content.value, signal)
}

defineExpose({ capture })
</script>

<style scoped>
.document-text-embed {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: var(--document-embed-height, auto);
  min-height: min(5rem, var(--document-embed-height, 5rem));
  max-height: var(--document-embed-height, min(24rem, 55dvh));
  overflow: hidden;
  border: 1px solid var(--rich-editor-border);
  border-radius: 8px;
  background: var(--rich-background);
  pointer-events: auto;
}
.document-text-embed-viewport {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  touch-action: pan-x pan-y;
}
.document-text-embed-content { padding: .6rem .75rem; }
</style>
