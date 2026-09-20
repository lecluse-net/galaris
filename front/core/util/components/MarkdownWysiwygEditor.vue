<template>
  <q-editor
    class="markdown-wysiwyg-editor"
    :class="{ 'markdown-wysiwyg-editor--auto-grow': autoGrow }"
    :model-value="htmlContent"
    :toolbar="editorToolbar"
    :min-height="minHeight"
    :max-height="autoGrow ? undefined : maxHeight"
    :aria-label="ariaLabel"
    :readonly="readonly"
    @update:model-value="updateHtmlContent"
  />
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { htmlToMarkdown, markdownToHtml } from '../markdownWysiwyg'

const {
  modelValue,
  minHeight = '240px',
  maxHeight = '70vh',
  ariaLabel = undefined,
  readonly = false,
  autoGrow = false,
} = defineProps<{
  modelValue: string
  minHeight?: string
  maxHeight?: string
  ariaLabel?: string
  readonly?: boolean
  autoGrow?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
}>()

const $q = useQuasar()
const htmlContent = ref(markdownToHtml(modelValue))
let lastEditorMarkdown = modelValue

const editorToolbar = [
  ['bold', 'italic', 'strike'],
  ['hr', 'link'],
  ['print', 'fullscreen'],
  [
    {
      icon: $q.iconSet.editor.formatting,
      options: ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'code'],
    },
    'removeFormat',
  ],
  ['quote', 'unordered', 'ordered', 'outdent', 'indent'],
  ['undo', 'redo'],
]

watch(() => modelValue, value => {
  const normalizedValue = value ?? ''
  if (normalizedValue === lastEditorMarkdown) return
  lastEditorMarkdown = normalizedValue
  htmlContent.value = markdownToHtml(normalizedValue)
})

function updateHtmlContent(value: string): void {
  htmlContent.value = value
  const markdown = htmlToMarkdown(value)
  lastEditorMarkdown = markdown
  emit('update:modelValue', markdown)
}
</script>

<style scoped>
.markdown-wysiwyg-editor {
  width: 100%;
}

.markdown-wysiwyg-editor :deep(.q-editor__content) {
  overflow-y: auto;
}

.markdown-wysiwyg-editor--auto-grow:not(.fullscreen) :deep(.q-editor__content) {
  max-height: none !important;
  overflow-y: visible;
}

.markdown-wysiwyg-editor :deep(.q-editor__content h1) {
  margin: 0.5em 0;
  font-size: 1.8em;
}

.markdown-wysiwyg-editor :deep(.q-editor__content h2) {
  margin: 0.4em 0;
  font-size: 1.5em;
}

.markdown-wysiwyg-editor :deep(.q-editor__content h3) {
  margin: 0.3em 0;
  font-size: 1.3em;
}

.markdown-wysiwyg-editor :deep(.q-editor__content h4) {
  margin: 0.3em 0;
  font-size: 1.1em;
}

.markdown-wysiwyg-editor :deep(.q-editor__content h5) {
  margin: 0.2em 0;
  font-size: 1em;
}

.markdown-wysiwyg-editor :deep(.q-editor__content h6) {
  margin: 0.2em 0;
  font-size: 0.9em;
}

.markdown-wysiwyg-editor :deep(.q-editor__content table) {
  width: 100%;
  border-collapse: collapse;
}

.markdown-wysiwyg-editor :deep(.q-editor__content th),
.markdown-wysiwyg-editor :deep(.q-editor__content td) {
  padding: 6px 8px;
  border: 1px solid rgba(0, 0, 0, 0.24);
  text-align: left;
}

body.body--dark .markdown-wysiwyg-editor :deep(.q-editor__content th),
body.body--dark .markdown-wysiwyg-editor :deep(.q-editor__content td) {
  border-color: rgba(255, 255, 255, 0.28);
}
</style>
