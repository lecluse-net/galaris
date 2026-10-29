<template>
  <CodeEditor v-model="model" language="json" :readonly="readonly" :label="label || t('documents.content')" :show-error="true" :visible-lines="24" />
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { CodeEditor } from '@/core/util'
defineOptions({ inheritAttrs: false })
const model = defineModel<string>({ required: true })
const { readonly = false, label = '' } = defineProps<{ readonly?: boolean; label?: string }>()
const { t } = useI18n()
</script>
