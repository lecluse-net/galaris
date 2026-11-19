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
      <q-card flat bordered>
      <q-splitter v-model="vertical" :limits="limits" class="gallery-splitter">
        <template #before><div class="q-pa-md">{{ t('graphicReference.before') }}</div></template>
        <template #separator><LibrarySplitterHandle v-model="vertical" :limits="limits" :label="t('graphicReference.resize')" /></template>
        <template #after>
          <q-splitter v-model="horizontal" horizontal :limits="limits" style="height: 240px">
            <template #before><div class="q-pa-md">{{ t('graphicReference.after') }}</div></template>
            <template #separator><LibrarySplitterHandle v-model="horizontal" horizontal :limits="limits" :label="t('graphicReference.resize')" /></template>
            <template #after><div class="q-pa-md">{{ t('graphicReference.details') }}</div></template>
          </q-splitter>
        </template>
      </q-splitter>
      </q-card>
      <q-separator spaced />
      <GraphViewControls class="inline-flex"><q-btn v-for="icon in ['add', 'remove', 'center_focus_strong']" :key="icon" flat round dense :icon="icon" :aria-label="icon" /></GraphViewControls>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { FolderIcon, GraphViewControls, LibrarySplitterHandle } from '@/core/util'
const { t } = useI18n()
const tab = ref('first'), vertical = ref(45), horizontal = ref(50)
const limits: [number, number] = [20, 80]
const nodes = computed(() => [{ key: 'root', label: t('graphicReference.before'), children: [{ key: 'child', label: t('graphicReference.sample') }] }])
</script>
<style scoped>
.inline-flex { display: inline-flex; }
</style>
