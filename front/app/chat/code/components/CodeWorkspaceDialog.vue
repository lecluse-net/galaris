<template>
  <q-dialog :model-value="true" maximized @update:model-value="!$event && emit('close')">
    <q-card class="galaris-dialog-card">
      <DialogHeader :title="title || t('code.title')" icon="code" :close-label="t('common.close')" />
      <q-separator />
      <div class="galaris-dialog-body galaris-dialog-body--contained">
        <div v-if="loading" class="flex flex-center fit"><q-spinner color="primary" size="42px" /></div>
        <q-banner v-else-if="error" class="q-ma-md" role="alert">
          {{ t(error) }}
          <template #action><q-btn v-if="canOpen" outline color="primary" :label="t('common.retry')" @click="retry++" /></template>
        </q-banner>
        <CodeWorkspacePane v-else-if="ready" :workspace-id="workspaceId" :show-toolbar="false" @hide="emit('close')" />
      </div>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePrivilegeStore } from '@/core/authorize'
import { DialogHeader } from '@/core/util'
import CodeWorkspacePane from './CodeWorkspacePane.vue'
import { useCodeStore } from '../stores/codeStore'
import { codeErrorTranslationKey } from '../services/codeService'

const props = defineProps<{ workspaceId: string; title: string }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const privileges = usePrivilegeStore()
const store = useCodeStore()
const canOpen = computed(() => privileges.hasPrivilege('CODE_ACCESS'))
const retry = ref(0)
const loading = ref(false)
const ready = ref(false)
const error = ref('')
watch([() => props.workspaceId, canOpen, retry], async ([id, allowed], _, onCleanup) => {
  let active = true
  onCleanup(() => { active = false })
  ready.value = false
  loading.value = allowed
  error.value = allowed ? '' : 'code.error'
  if (!allowed) return
  try {
    await store.open(id, undefined, 'files')
    if (active) ready.value = true
  } catch (cause) {
    if (active) error.value = codeErrorTranslationKey(cause)
  } finally {
    if (active) loading.value = false
  }
}, { immediate: true })
</script>
