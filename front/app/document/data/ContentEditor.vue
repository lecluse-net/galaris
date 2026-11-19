<template>
  <CodeEditor v-model="model" language="json" fill-height :readonly="readonly" :label="label || t('documents.content')" :show-error="true">
    <template #toolbar="{ copy, languageLabel }">
      <DocumentToolbar :label="label || t('documents.content')" :readonly="readonly"
        :groups="[{ id: 'json', label: languageLabel, commands: [
          { id: 'copy', kind: 'button', label: t('common.copy'), icon: 'content_copy', showLabel: true, readOnly: true },
        ] }]" @command="copy" />
    </template>
  </CodeEditor>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { CodeEditor } from '@/core/util'
import { DocumentToolbar } from '@/core/util/facade'
defineOptions({ inheritAttrs: false })
const model = defineModel<string>({ required: true })
const { readonly = false, label = '' } = defineProps<{ readonly?: boolean; label?: string }>()
const { t } = useI18n()
</script>
