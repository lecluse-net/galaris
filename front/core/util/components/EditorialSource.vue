<template>
  <div class="galaris-source-editing-area">
    <pre ref="mirror" class="galaris-source-highlight" aria-hidden="true"><code v-html="highlighted" /></pre>
    <textarea ref="input" :value="modelValue" :readonly="readonly" :aria-label="label" spellcheck="false" @input="change" @scroll="scroll" />
  </div>
</template>
<script setup lang="ts">
import { computed, useTemplateRef } from 'vue'
import { highlightCode } from '../codeHighlight'
const { modelValue, readonly = false, label } = defineProps<{ modelValue: string; readonly?: boolean; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const mirror = useTemplateRef('mirror'), input = useTemplateRef('input')
const highlighted = computed(() => (highlightCode(modelValue, 'xml') ?? modelValue.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')) + ' ')
function change(event: Event): void { emit('update:modelValue', (event.target as HTMLTextAreaElement).value) }
function scroll(): void { if (mirror.value && input.value) { mirror.value.scrollTop = input.value.scrollTop; mirror.value.scrollLeft = input.value.scrollLeft } }
</script>
