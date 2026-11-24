<template>
  <q-list dense separator bordered>
    <q-item v-for="relation in relations" :key="relation.edge.id" clickable @click="emit('select', relation.other.id)">
      <q-item-section avatar>
        <DocumentIcon v-if="relation.other.node_kind === 'document'" :document-id="relation.other.id" :title="relation.other.title" />
        <q-icon v-else name="account_tree" color="primary" />
      </q-item-section>
      <q-item-section>
        <q-item-label>{{ relation.other.title }}</q-item-label>
        <q-item-label caption>{{ relationLabel(relation.edge.relation_type) }}</q-item-label>
      </q-item-section>
      <q-item-section side><q-icon name="chevron_right" /></q-item-section>
    </q-item>
  </q-list>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { DocumentIcon } from '@/app/document'
import type { MemoryGraphRelation } from '../types'

defineProps<{ relations: MemoryGraphRelation[] }>()
const emit = defineEmits<{ select: [id: string] }>()
const { t, te } = useI18n()

function relationLabel(relation: string): string {
  const key = `memory.relationTypes.${relation}`
  return te(key) ? t(key) : t('memory.otherRelation')
}
</script>
