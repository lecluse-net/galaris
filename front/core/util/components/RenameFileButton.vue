<template>
  <q-btn v-bind="$attrs" flat round dense icon="drive_file_rename_outline" :disable="disabled || saving"
    :aria-label="t('fileRename.action', { name })" @click.stop="openDialog">
    <q-tooltip>{{ t('fileRename.label') }}</q-tooltip>
  </q-btn>
  <q-dialog v-model="open">
    <q-card class="galaris-dialog-card" style="width: 480px; max-width: 95vw">
      <q-form @submit="save">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ title || t('fileRename.title') }}</div><q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>
          <q-input v-model="draft" outlined autofocus :label="nameLabel || t('fileRename.name')" :disable="saving"
            maxlength="500" :error="Boolean(validationError)" :error-message="validationError" />
          <q-banner v-if="error" class="q-mt-sm" role="alert">{{ error }}</q-banner>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline :label="t('common.cancel')" />
          <q-btn color="primary" type="submit" :label="t('fileRename.save')" :loading="saving"
            :disable="Boolean(validationError) || draft.trim() === name" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'

defineOptions({ inheritAttrs: false })

const { name, rename, disabled = false, title = '', nameLabel = '' } = defineProps<{
  name: string
  rename: (name: string) => Promise<unknown>
  disabled?: boolean
  title?: string
  nameLabel?: string
}>()
const { t } = useI18n()
const open = ref(false), saving = ref(false), draft = ref(''), error = ref('')
let generation = 0
const validationError = computed(() => {
  const value = draft.value.trim()
  return !value || value.length > 500 || ['.', '..'].includes(value) || /[/\\\p{Cc}]/u.test(value)
    ? t('fileRename.invalid') : ''
})
function openDialog(): void {
  if (disabled || saving.value) return
  draft.value = name; error.value = ''; open.value = true
}
async function save(): Promise<void> {
  if (disabled || saving.value || validationError.value || draft.value.trim() === name) return
  const request = generation
  saving.value = true; error.value = ''
  try {
    await rename(draft.value.normalize('NFC').trim())
    if (request === generation) open.value = false
  } catch (cause) {
    if (request === generation) error.value = apiErrorDetail(cause) ?? t('fileRename.error')
  } finally { saving.value = false }
}
watch(() => name, () => { generation++; open.value = false })
onBeforeUnmount(() => { generation++ })
defineExpose({ open: openDialog })
</script>
