<template>
  <div class="row q-col-gutter-lg">
    <div class="col-12 col-md-6">
      <q-breadcrumbs :aria-label="t('graphicReference.breadcrumbs')"><q-breadcrumbs-el icon="home" :label="t('graphicReference.first')" /><q-breadcrumbs-el :label="t('graphicReference.second')" /></q-breadcrumbs>
      <q-tabs v-model="tab" active-color="primary" class="q-mt-md" dense><q-tab v-for="key in ['first', 'second']" :key="key" :name="key" :label="t(`graphicReference.${key}`)" /></q-tabs>
      <q-tab-panels v-model="tab"><q-tab-panel v-for="key in ['first', 'second']" :key="key" :name="key">{{ t(`graphicReference.${key}`) }}</q-tab-panel></q-tab-panels>
      <q-expansion-item icon="folder" :label="t('graphicReference.expansion')" default-opened><div class="q-pa-md">{{ t('graphicReference.details') }}</div></q-expansion-item>
      <q-tree :nodes="nodes" node-key="key" default-expand-all :aria-label="t('graphicReference.tree')"><template #default-header="scope"><FolderIcon :expanded="scope.expanded" size="22px" /><span class="q-ml-sm">{{ scope.node.label }}</span></template></q-tree>
    </div>
    <div class="col-12 col-md-6">
      <q-splitter v-model="vertical" :limits="[20, 80]" class="gallery-splitter" :separator-style="{ background: 'var(--solaire-gray-light)' }">
        <template #before><div class="q-pa-md">{{ t('graphicReference.before') }}</div></template>
        <template #separator><DocumentSplitterHandle role="separator" tabindex="0" aria-orientation="vertical" :aria-label="t('graphicReference.resize')" :aria-valuenow="vertical" :aria-valuemin="20" :aria-valuemax="80" @keydown="resize($event, false)" /></template>
        <template #after>
          <q-splitter v-model="horizontal" horizontal :limits="[20, 80]" style="height: 240px">
            <template #before><div class="q-pa-md">{{ t('graphicReference.after') }}</div></template>
            <template #separator><DocumentSplitterHandle horizontal role="separator" tabindex="0" aria-orientation="horizontal" :aria-label="t('graphicReference.resize')" :aria-valuenow="horizontal" :aria-valuemin="20" :aria-valuemax="80" @keydown="resize($event, true)" /></template>
            <template #after><div class="q-pa-md">{{ t('graphicReference.details') }}</div></template>
          </q-splitter>
        </template>
      </q-splitter>
      <q-separator spaced />
      <GraphViewControls class="inline-flex"><q-btn v-for="icon in ['add', 'remove', 'center_focus_strong']" :key="icon" flat round dense :icon="icon" :aria-label="icon" /></GraphViewControls>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { FolderIcon, GraphViewControls } from '@/core/util'
import { DocumentSplitterHandle } from '../../../graphicReferenceContributions'
const { t } = useI18n()
const tab = ref('first'), vertical = ref(45), horizontal = ref(50)
const nodes = computed(() => [{ key: 'root', label: t('graphicReference.before'), children: [{ key: 'child', label: t('graphicReference.sample') }] }])
function resize(event: KeyboardEvent, isHorizontal: boolean): void {
  const previous = isHorizontal ? 'ArrowUp' : 'ArrowLeft', next = isHorizontal ? 'ArrowDown' : 'ArrowRight'
  if (![previous, next, 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const model = isHorizontal ? horizontal : vertical
  model.value = event.key === 'Home' ? 20 : event.key === 'End' ? 80 : Math.min(80, Math.max(20, model.value + (event.key === previous ? -5 : 5)))
}
</script>
<style scoped>
.gallery-splitter { border: 1px solid var(--solaire-gray-accent); border-radius: 6px; }
.inline-flex { display: inline-flex; }
</style>
