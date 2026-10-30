<template>
  <q-card class="gallery-dialog-card galaris-dialog-card">
    <q-card-section class="galaris-dialog-title row items-center no-wrap">
      <span class="text-h6">{{ t('graphicReference.modalTitle') }}</span><q-space />
      <q-btn flat round dense icon="close" :aria-label="t('graphicReference.close')" @click="emit('close')" />
    </q-card-section>
    <q-card-section class="galaris-dialog-body">
      <p>{{ t('graphicReference.modalText') }}</p>
      <q-input v-model="name" outlined dense :label="t('graphicReference.name')" />
    </q-card-section>
    <q-separator />
    <q-card-actions align="right" class="galaris-dialog-actions q-pa-md">
      <q-btn outline color="primary" :label="t('graphicReference.cancel')" @click="emit('close')" />
      <q-btn color="primary" :label="t('graphicReference.save')" @click="emit('save')" />
    </q-card-actions>
  </q-card>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
const name = ref('')
const emit = defineEmits<{ close: []; save: [] }>()
</script>
<style scoped>
.gallery-dialog-card { width: 100%; max-width: 460px; }
</style>
