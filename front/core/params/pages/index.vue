<template>
  <q-page class="preferences-home q-pa-md">
    <PageHeader :icon="navigationIcon('settings')" :title="t('configuration.home.title')" :description="t('configuration.home.description')" />

    <PreferencesMenuGrid :items="menuItems" />
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon, useNavigation } from '@/core/navigation'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { PageHeader } from '@/core/util'
import PreferencesMenuGrid from '../components/PreferencesMenuGrid.vue'
import { preferenceSections } from '../presentation'

const { t } = useI18n()
const { findByPath, getSortedNodes } = useNavigation()
const menuItems = computed(() => getSortedNodes(findByPath('admin.params')?.children ?? {})
  .filter(node => node.to)
  .map(node => {
    const section = preferenceSections.find(section => section.key === node.key)
    return {
      key: node.key,
      title: t(node.label ?? ''),
      description: node.description ? t(node.description) : '',
      icon: node.icon ?? 'settings',
      to: node.to!,
      color: section?.color ?? 'red' as const,
    }
  }))
</script>

<style scoped>
.preferences-home {
  min-width: 0;
}
</style>
