<template>
  <div class="chat-profile-preferences">
    <q-card v-if="chatAvailable === true" flat bordered>
      <q-card-section class="row items-center q-gutter-sm">
        <q-icon name="forum" color="primary" size="sm" />
        <div class="text-h6">{{ t('nav.chat') }}</div>
      </q-card-section>
      <q-separator />
      <q-card-section>
        <q-select
          :model-value="authStore.user?.document_open_mode ?? 'split'"
          :options="documentOpenModeOptions"
          :label="t('user.profile.documentOpenMode')"
          :hint="t('user.profile.documentOpenModeHint')"
          :loading="saving"
          :disable="saving"
          emit-value
          map-options
          outlined
          dense
          @update:model-value="setDocumentOpenMode"
        />
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useAuthStore, type DocumentOpenMode } from '@/core/user'
import { chatAvailable, refreshChatAvailability } from '../availability'

const authStore = useAuthStore()
const { t } = useI18n()
const $q = useQuasar()
const saving = ref(false)
const documentOpenModeOptions = computed(() => [
  { label: t('user.profile.documentOpenModeSplit'), value: 'split' },
  { label: t('user.profile.documentOpenModeDialog'), value: 'dialog' },
])

async function setDocumentOpenMode(mode: DocumentOpenMode): Promise<void> {
  saving.value = true
  try {
    await authStore.updateProfile({ document_open_mode: mode })
  } catch {
    $q.notify({ type: 'negative', message: t('user.profile.updateError') })
  } finally {
    saving.value = false
  }
}

onMounted(() => void refreshChatAvailability())
</script>

<style scoped>
.chat-profile-preferences { display: contents; }
</style>
