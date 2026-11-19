<template>
  <div :class="toolbar ? 'editorial-toolbar-row no-wrap' : 'row items-center no-wrap q-gutter-x-xs'">
    <q-btn v-bind="appearance" dense icon="arrow_back" :disable="!canGoBack" :aria-label="t('documents.previousDocument')" @click="emit('back')">
      <q-tooltip>{{ t('documents.previousDocument') }}</q-tooltip>
    </q-btn>
    <q-btn v-bind="appearance" dense icon="arrow_forward" :disable="!canGoForward" :aria-label="t('documents.nextDocument')" @click="emit('forward')">
      <q-tooltip>{{ t('documents.nextDocument') }}</q-tooltip>
    </q-btn>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'

const { toolbar = false } = defineProps<{ canGoBack: boolean; canGoForward: boolean; toolbar?: boolean }>()
const emit = defineEmits<{ back: []; forward: [] }>()
const { t } = useI18n()
const $q = useQuasar()
const appearance = computed(() => toolbar
  ? { flat: true }
  : { outline: true, round: true, color: 'primary', class: $q.dark.isActive ? 'bg-dark' : 'bg-white' })
</script>
