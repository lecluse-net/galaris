<template>
  <div class="row items-center no-wrap q-gutter-x-xs">
    <q-btn outline round dense color="primary" :class="$q.dark.isActive ? 'bg-dark' : 'bg-white'" icon="arrow_back" :disable="!canGoBack" :aria-label="t('documents.previousDocument')" @click="emit('back')">
      <q-tooltip>{{ t('documents.previousDocument') }}</q-tooltip>
    </q-btn>
    <q-btn outline round dense color="primary" :class="$q.dark.isActive ? 'bg-dark' : 'bg-white'" icon="arrow_forward" :disable="!canGoForward" :aria-label="t('documents.nextDocument')" @click="emit('forward')">
      <q-tooltip>{{ t('documents.nextDocument') }}</q-tooltip>
    </q-btn>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{ canGoBack: boolean; canGoForward: boolean }>()
const emit = defineEmits<{ back: []; forward: [] }>()
const { t } = useI18n()
</script>
