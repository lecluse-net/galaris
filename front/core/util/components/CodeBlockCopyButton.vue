<template>
  <q-btn flat round dense size="sm" :icon="editorialIcon('copy', 'content_copy')" :aria-label="t('richEditor.codeTools.copy')" :title="t('richEditor.codeTools.copy')" :loading="copying" @click.stop="copy" />
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { editorialIcon } from '../editorialIcons'

const { source } = defineProps<{ source: () => string }>()
const { t } = useI18n(), $q = useQuasar(), copying = ref(false)
let active = true
onBeforeUnmount(() => { active = false })
async function copy(): Promise<void> {
  if (copying.value) return
  copying.value = true
  try {
    await copyToClipboard(source())
    if (active) $q.notify({ type: 'positive', message: t('richEditor.codeTools.copied') })
  } catch {
    if (active) $q.notify({ type: 'negative', message: t('richEditor.codeTools.copyFailed') })
  } finally { copying.value = false }
}
</script>
