<template>
  <q-dialog :ref="dialog.dialogRef" :aria-labelledby="titleId" @hide="dialog.onDialogHide">
    <q-card class="q-dialog-plugin">
      <q-card-section class="galaris-dialog-title">
        <div :id="titleId" class="text-h6">{{ title || t('common.confirm') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section class="confirmation-message">{{ message }}</q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn v-if="cancel" v-bind="cancelProps" :data-autofocus="focus === 'cancel' || undefined" @click="dialog.onDialogCancel" />
        <q-btn v-if="ok" v-bind="okProps" :data-autofocus="focus === 'ok' || undefined" @click="dialog.onDialogOK()" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, useId } from 'vue'
import { useDialogPluginComponent, useQuasar, type QBtnProps } from 'quasar'
import { useI18n } from 'vue-i18n'
import type { ConfirmationDialogOptions } from '../confirmationDialog'

const { title, message, ok = true, cancel = false, focus = 'ok', color = 'primary' } = defineProps<ConfirmationDialogOptions>()
defineEmits([...useDialogPluginComponent.emits])
const dialog = useDialogPluginComponent()
const { t } = useI18n()
const $q = useQuasar()
const titleId = useId()

function buttonProps(value: boolean | string | QBtnProps, label: string): QBtnProps {
  return { flat: true, color, label: typeof value === 'string' ? value : label,
    ...(typeof value === 'object' ? value : {}) }
}
const okProps = computed(() => buttonProps(ok, $q.lang.label.ok))
const cancelProps = computed(() => buttonProps(cancel, t('common.cancel')))
</script>

<style scoped>
.confirmation-message { white-space: pre-line; overflow-wrap: anywhere; }
</style>
