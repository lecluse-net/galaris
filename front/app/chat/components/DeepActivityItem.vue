<template>
  <q-expansion-item dense dense-toggle :label="block.name || t('chat.deep.detail')"
    :caption="t(`chat.deep.${block.state}`)"
  >
    <pre v-if="block.output" class="deep-output">{{ block.output }}</pre>
    <pre v-if="block.details && block.details !== block.output" class="deep-output">{{ block.details }}</pre>
    <DeepActivityItem v-for="child in blocks[block.id] ?? []" :key="child.id" :block="child" :blocks="blocks" />
  </q-expansion-item>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { DeepActivityBlock } from '../deepActivity'

defineProps<{ block: DeepActivityBlock; blocks: Record<string, DeepActivityBlock[]> }>()
const { t } = useI18n()
</script>

<style scoped>
.deep-output { max-block-size: 24rem; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; padding: .5rem; }
</style>
