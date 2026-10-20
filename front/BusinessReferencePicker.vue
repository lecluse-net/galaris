<template>
  <div class="reference-picker col column q-pa-sm">
    <q-input v-model="query" outlined dense clearable debounce="250" :label="t('richEditor.referenceSearch')">
      <template #prepend><q-icon name="search" /></template>
      <template #append><q-spinner v-if="loading" color="primary" role="status" /></template>
    </q-input>
    <q-banner v-if="error" role="alert">
      {{ t('richEditor.resources.failed') }}
      <template #action><q-btn outline :label="t('common.retry')" @click="search" /></template>
    </q-banner>
    <q-list v-if="!error" class="col scroll q-mt-sm" separator>
      <q-item v-for="item in items" :key="item.uri" clickable :disable="busy" @click="emit('select', item)">
        <q-item-section><q-item-label>{{ item.title }}</q-item-label><q-item-label caption>{{ item.context }}</q-item-label></q-item-section>
        <q-item-section side><q-icon name="link" /><q-tooltip>{{ item.uri }}</q-tooltip></q-item-section>
      </q-item>
      <q-item v-if="!items.length && !loading"><q-item-section>{{ t('richEditor.noReferences') }}</q-item-section></q-item>
    </q-list>
  </div>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { searchRichLinks, type RichLinkTarget } from '@/core/util/richText'
import { useReferenceFormatting } from '@/core/util'
defineProps<{ busy?: boolean }>()
const emit = defineEmits<{ select: [value: RichLinkTarget] }>()
const { t } = useI18n()
const referenceFormatting = useReferenceFormatting()
const query = ref<string | null>(''), items = ref<RichLinkTarget[]>([]), loading = ref(false), error = ref(false)
let generation = 0
async function search(): Promise<void> {
  const current = ++generation
  loading.value = true; error.value = false
  try { const found = await searchRichLinks(query.value?.trim() ?? '', 'galaris', referenceFormatting()); if (current === generation) items.value = found }
  catch { if (current === generation) { error.value = true; items.value = [] } }
  finally { if (current === generation) loading.value = false }
}
watch(query, search, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<style scoped>
.reference-picker { min-height: 0; overflow: hidden; }
</style>
