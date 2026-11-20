<template>
  <q-card flat bordered class="danger-card">
    <q-card-section class="row items-center q-gutter-md">
      <q-icon name="warning_amber" color="negative" size="sm" />
      <div class="col" style="min-width: 0">
        <div class="text-subtitle2 text-negative">{{ t('userEdit.dangerTitle') }}</div>
        <div class="text-caption text-grey-7">{{ t('userEdit.dangerZone') }}</div>
      </div>
      <q-btn

        color="negative"
        icon="delete"
        :label="t('userEdit.deleteAccount')"
        :loading="loading"
        @click="confirmationOpen = true"
      />
    </q-card-section>
  </q-card>

  <q-dialog data-confirmation v-model="confirmationOpen">
    <q-card class="account-deletion-dialog galaris-dialog-card">
      <DialogHeader :title="t('userEdit.deleteAccountTitle')" :close-label="t('common.close')" />

      <q-card-section class="galaris-dialog-body">
        {{ t('userEdit.deleteAccountConfirm') }}
      </q-card-section>

      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn outline  color="primary" :label="t('common.cancel')" v-close-popup />
        <q-btn data-autofocus

          color="negative"
          icon="delete"
          :label="t('common.delete')"
          :loading="loading"
          @click="confirmDelete"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { DialogHeader } from '@/core/util/facade'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { loading = false } = defineProps<{
  loading?: boolean
}>()
const emit = defineEmits<{
  delete: []
}>()

const { t } = useI18n()
const confirmationOpen = ref(false)

function confirmDelete(): void {
  emit('delete')
}
</script>

<style scoped>
.danger-card {
  border-color: color-mix(in srgb, var(--q-negative) 45%, transparent);
}

.account-deletion-dialog {
  width: min(520px, calc(100vw - 32px));
}
</style>
