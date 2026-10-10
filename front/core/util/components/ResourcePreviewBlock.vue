<template>
  <article class="resource-preview-card resource-preview-block" :class="`resource-preview-block--${placement}`">
    <div class="resource-preview-visual">
      <slot name="preview">
        <img v-if="image" :src="image" :alt="title" class="resource-preview-thumbnail" />
        <div v-else class="resource-preview-icon"><q-icon :name="icon" size="32px" /></div>
      </slot>
    </div>
    <div class="resource-preview-copy">
      <div class="resource-preview-title"><span v-if="$slots['title-icon']" class="resource-preview-title-icon"><slot name="title-icon" /></span>{{ title }}</div>
      <div v-if="plainDescription" class="resource-preview-description">{{ plainDescription }}</div>
      <div v-if="subtitle" class="resource-preview-subtitle">{{ subtitle }}</div>
      <div v-if="uri" class="resource-preview-uri">{{ uri }}</div>
    </div>
    <component
      v-if="!disabled"
      :is="href ? 'a' : 'button'"
      :href="href"
      :target="href ? '_blank' : undefined"
      :type="href ? undefined : 'button'"
      rel="noopener noreferrer"
      class="resource-preview-main"
      :aria-label="openLabel"
      @click="emit('open', $event)"
    />
    <div v-if="$slots.actions" class="resource-preview-actions"><slot name="actions" /></div>
    <div v-if="$slots.player" class="resource-preview-player"><slot name="player" /></div>
  </article>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import '../resourcePreviewCard.css'

const { placement = 'below-page', icon = 'insert_drive_file', description = '' } = defineProps<{
  placement?: 'in-page' | 'below-page'
  title: string
  description?: string
  subtitle?: string
  uri?: string
  image?: string
  icon?: string
  href?: string
  openLabel: string
  disabled?: boolean
}>()
const plainDescription = computed(() => {
  const content = DOMPurify.sanitize(marked.parse(description, { async: false }), {
    RETURN_DOM_FRAGMENT: true,
    ALLOWED_TAGS: ['p', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li', 'table', 'tr', 'th', 'td', 'pre', 'code', 'a', 'strong', 'em', 'span'],
    ALLOWED_ATTR: [],
  })
  for (const block of content.querySelectorAll('p,div,br,h1,h2,h3,h4,h5,h6,blockquote,li,tr,th,td,pre')) block.append(' ')
  return content.textContent?.replace(/\s+/g, ' ').trim() ?? ''
})
const emit = defineEmits<{ open: [event: MouseEvent] }>()
</script>
<style scoped>
.resource-preview-title-icon { position: relative; z-index: 2; display: inline-flex; vertical-align: middle; margin-right: 8px; }
</style>
