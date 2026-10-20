<template>
  <q-btn flat round dense icon="link" :aria-label="t('richEditor.copy')" @click.stop="copy(uri)">
    <q-tooltip>{{ t('richEditor.copy') }}</q-tooltip>
  </q-btn>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useResourceCopy } from '../resourceCopy'
defineProps<{ uri: string }>()
const { t } = useI18n(), { copy } = useResourceCopy()
</script>
