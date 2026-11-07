<template>
  <q-dialog v-model="open">
    <q-card class="galaris-dialog-card" style="width: 560px; max-width: 92vw">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('agent.generateAvatar') }}</div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup :aria-label="t('common.close')" />
      </q-card-section>
      <q-form @submit="emit('generate', instructions.trim())">
        <q-card-section class="galaris-dialog-body">
          <p>{{ t('agent.avatarInstructionsHelp') }}</p>
          <q-input
            v-model="instructions"
            outlined
            type="textarea"
            rows="5"
            autofocus
            counter
            maxlength="4000"
            :label="t('agent.avatarInstructions')"
            :placeholder="t('agent.avatarInstructionsPlaceholder')"
            :disable="loading"
          />
          <p class="text-caption q-mb-none">{{ t('agent.avatarReplacementHelp') }}</p>
          <q-banner v-if="error" class="q-mt-md" role="alert">{{ error }}</q-banner>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right" class="galaris-dialog-actions q-pa-md">
          <q-btn outline color="primary" :label="t('common.cancel')" v-close-popup />
          <q-btn color="primary" icon="auto_awesome" type="submit" :label="t('agent.generateAvatar')" :loading="loading" :disable="loading" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

defineProps<{ loading: boolean; error: string }>()
const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ generate: [instructions: string] }>()
const { t } = useI18n()
const instructions = ref('')
watch(open, value => { if (value) instructions.value = '' })
</script>
