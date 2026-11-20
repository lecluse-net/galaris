<template>
  <q-dialog data-confirmation :ref="dialog.dialogRef" :aria-labelledby="titleId" @show="focusAction" @hide="dialog.onDialogHide">
    <q-card class="q-dialog-plugin galaris-dialog-card">
      <DialogHeader :title="title || t('common.confirm')" :title-id="titleId" />
      <q-card-section class="confirmation-message galaris-dialog-body">{{ message }}</q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn v-if="cancel" v-bind="cancelProps" @click="dialog.onDialogCancel" />
        <q-btn v-if="ok" ref="okAction" v-bind="okProps" data-autofocus @click="dialog.onDialogOK()" />
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

const { title, message, ok = true, cancel = false, color = 'primary', flatActions = false } = defineProps<ConfirmationDialogOptions>()
defineEmits([...useDialogPluginComponent.emits])
const dialog = useDialogPluginComponent()
const { t } = useI18n()
const $q = useQuasar()
const titleId = useId()
const okAction = useTemplateRef<QBtn>('okAction')

function focusAction(): void {
  // Route traversal and a parent dialog can move focus during the transition.
  const action = okAction.value?.$el
  if (action instanceof HTMLElement) action.focus({ preventScroll: true })
}

function buttonProps(value: boolean | string | QBtnProps, label: string): QBtnProps {
  const props: QBtnProps = { color, label: typeof value === 'string' ? value : label,
    ...(typeof value === 'object' ? value : {}) }
  props.flat = flatActions
  props.outline = !flatActions && props.color !== 'negative'
  return props
}
const okProps = computed(() => buttonProps(ok, $q.lang.label.ok))
const cancelProps = computed(() => buttonProps(cancel, t('common.cancel')))
</script>

<style scoped>
.confirmation-message { white-space: pre-line; overflow-wrap: anywhere; }
</style>
