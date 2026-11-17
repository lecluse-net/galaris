<template>
  <q-btn
    :flat="iconOnly"
    :round="iconOnly"
    :outline="!iconOnly"
    :size="iconOnly ? 'sm' : undefined"
    color="primary"
    icon="network_check"
    :label="iconOnly ? undefined : t('connection.test.button')"
    :aria-label="iconOnly ? t('connection.test.button') : undefined"
    :loading="loading"
    @click.stop="test"
  >
    <q-tooltip>{{ t(iconOnly ? 'connection.test.button' : 'connection.test.savedSettings') }}</q-tooltip>
  </q-btn>
  <q-dialog v-model="showResult">
    <q-card class="galaris-dialog-card connection-test-dialog">
      <DialogHeader :title="t('connection.test.title')" :close-label="t('common.close')" />
      <q-card-section class="galaris-dialog-body" aria-live="polite">
        <p class="text-weight-medium">{{ t(`connection.test.${result?.status ?? 'error'}`) }}</p>
        <q-list v-if="result" separator>
          <q-item v-for="check in result.checks" :key="check.protocol">
            <q-item-section avatar><q-icon :name="check.status === 'success' ? 'check_circle' : check.status === 'error' ? 'error' : 'help_outline'"
              :color="check.status === 'success' ? 'positive' : check.status === 'error' ? 'negative' : 'primary'" /></q-item-section>
            <q-item-section><q-item-label>{{ t(`connection.test.protocols.${check.protocol}`) }}</q-item-label>
              <q-item-label caption>{{ check.message }}</q-item-label></q-item-section>
          </q-item>
        </q-list>
        <p v-else role="alert">{{ error }}</p>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { DialogHeader } from '@/core/util'
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import connectionService, { type ConnectionTestResult } from '../services/connectionService'

const props = defineProps<{ connectionId: number; iconOnly?: boolean }>()
const { t } = useI18n()
const loading = ref(false), showResult = ref(false), error = ref('')
const result = ref<ConnectionTestResult | null>(null)
let generation = 0
function reset() { generation++; loading.value = false; showResult.value = false; result.value = null }
watch(() => props.connectionId, reset)
onBeforeUnmount(reset)
async function test() {
  if (loading.value) return
  const current = ++generation
  loading.value = true; result.value = null; error.value = ''
  try {
    const { data } = await connectionService.testConnection(props.connectionId)
    if (current === generation) { result.value = data; showResult.value = true }
  } catch {
    if (current === generation) { error.value = t('connection.test.requestError'); showResult.value = true }
  } finally { if (current === generation) loading.value = false }
}
</script>

<style scoped>
.connection-test-dialog { width: min(640px, calc(100vw - 32px)); max-width: 640px; }
</style>
