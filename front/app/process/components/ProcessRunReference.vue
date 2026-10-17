<template>
  <a class="run-reference" :href="nativeProcessService.runUrl(id)" :aria-label="t('nativeProcesses.copyRunUrl') + ': ' + id" @click.stop.prevent="copy">
    {{ id }}
    <q-tooltip>{{ t('nativeProcesses.copyRunUrl') }}</q-tooltip>
  </a>
</template>

<script setup lang="ts">
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { nativeProcessService } from '../services/nativeProcessService'

const props = defineProps<{ id: string }>()
const { t } = useI18n(), $q = useQuasar()
async function copy(): Promise<void> {
  try { await copyToClipboard(nativeProcessService.runUrl(props.id)); $q.notify({ type: 'positive', message: t('common.copied'), timeout: 1500 }) }
  catch { $q.notify({ type: 'negative', message: t('common.copyError') }) }
}
</script>

<style scoped>
.run-reference { color: var(--q-primary); font-family: monospace; text-decoration: none; overflow-wrap: anywhere; }
</style>
