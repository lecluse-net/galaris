<template>
  <q-dialog :ref="dialog.dialogRef" :aria-labelledby="titleId" @show="focusAction" @hide="dialog.onDialogHide">
    <q-card class="q-dialog-plugin galaris-dialog-card">
      <DialogHeader :title="title || t('common.confirm')" :title-id="titleId" />
      <q-card-section class="confirmation-message galaris-dialog-body">{{ message }}</q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn v-if="cancel" ref="cancelAction" v-bind="cancelProps" :data-autofocus="focus === 'cancel' || undefined" @click="dialog.onDialogCancel" />
        <q-btn v-if="ok" ref="okAction" v-bind="okProps" :data-autofocus="focus === 'ok' || undefined" @click="dialog.onDialogOK()" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, useId, useTemplateRef } from 'vue'
import { useDialogPluginComponent, useQuasar, type QBtn, type QBtnProps } from 'quasar'
import { useI18n } from 'vue-i18n'
import type { ConfirmationDialogOptions } from '../confirmationDialog'
import DialogHeader from './DialogHeader.vue'

const { title, message, ok = true, cancel = false, focus = 'ok', color = 'primary' } = defineProps<ConfirmationDialogOptions>()
defineEmits([...useDialogPluginComponent.emits])
const dialog = useDialogPluginComponent()
const { t } = useI18n()
const $q = useQuasar()
const titleId = useId()
const cancelAction = useTemplateRef<QBtn>('cancelAction')
const okAction = useTemplateRef<QBtn>('okAction')

function focusAction(): void {
  // Route traversal and a parent dialog can move focus during the transition.
  if (focus === 'none') return
  const action = (focus === 'cancel' ? cancelAction : okAction).value?.$el
  if (action instanceof HTMLElement) action.focus({ preventScroll: true })
}

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
