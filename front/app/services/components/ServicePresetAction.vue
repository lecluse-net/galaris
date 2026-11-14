<template>
  <div class="column items-start q-gutter-xs">
    <span v-if="existing" class="text-caption">{{ t(newer ? 'services.catalogUpdateAvailable' : 'services.catalogInstalled') }}</span>
    <span v-if="!entry.compatible" class="text-caption">{{ t(`services.catalogCompatibility.${entry.compatibility}`) }}</span>
    <q-btn v-if="canEdit" color="primary" outline icon="add" :label="t('services.usePreset')" :disable="!entry.compatible" @click="select" />
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Service, ServiceCreate, ServicePreset } from '../services/serviceApi'
const { entry, installed, canEdit } = defineProps<{ entry: ServicePreset; installed: Service[]; canEdit: boolean }>()
const emit = defineEmits<{ select: [definition: ServiceCreate] }>()
const { t } = useI18n()
const existing = computed(() => installed.find(service => service.code === entry.definition.code))
const newer = computed(() => existing.value?.catalog && existing.value.catalog.version !== entry.definition.catalog?.version)
function select() {
  if (!canEdit || !entry.compatible) return
  const definition: ServiceCreate = JSON.parse(JSON.stringify(entry.definition))
  // A new local copy always has its own identity; it never overwrites an installed service.
  let suffix = 2
  while (installed.some(service => service.code === definition.code)) definition.code = `${entry.definition.code}-${suffix++}`
  emit('select', definition)
}
</script>
