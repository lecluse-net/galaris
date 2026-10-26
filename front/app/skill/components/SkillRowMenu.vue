<template>
  <ActionContextMenu :target="target" :actions="actions" :label="skill.label">
    <template v-if="canEdit">
      <q-separator />
      <q-item clickable role="menuitem" :aria-label="t('skills.categories.assign')">
        <q-item-section avatar><q-icon name="drive_file_move" /></q-item-section>
        <q-item-section>{{ t('skills.categories.assign') }}</q-item-section>
        <q-item-section side><q-icon name="chevron_right" /></q-item-section>
        <ContextSubmenu>
          <q-list dense role="menu" :aria-label="t('skills.categories.assign')">
            <q-item v-for="category in categoryOptions" :key="category.id ?? 'none'" v-close-popup="2" clickable
              role="menuitem" :active="skill.category_id === category.id" @click="assign(category.id)">
              <q-item-section avatar><q-icon :name="skill.category_id === category.id ? 'check' : 'folder'" /></q-item-section>
              <q-item-section>{{ category.label }}</q-item-section>
            </q-item>
          </q-list>
        </ContextSubmenu>
      </q-item>
    </template>
  </ActionContextMenu>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ActionContextMenu, ContextSubmenu, type ContextAction } from '@/core/util'
import type { Skill, SkillCategory } from '../services/skillService'

const { skill, target, canEdit, categories } = defineProps<{
  skill: Skill; target: string; canEdit: boolean; categories: SkillCategory[]
}>()
const emit = defineEmits<{
  view: [skill: Skill]; edit: [skill: Skill]; personal: [skill: Skill]
  download: [skill: Skill]; delete: [skill: Skill]; category: [skill: Skill, category: number | null]
  toggle: [skill: Skill]
}>()
const { t } = useI18n()
const categoryOptions = computed(() => [{ id: null, label: t('skills.categories.none') }, ...categories])
const actions = computed<ContextAction[]>(() => [
  { key: 'view', label: t('skills.view'), icon: 'visibility', run: () => emit('view', skill) },
  ...(canEdit && !skill.system ? [
    { key: 'edit', label: t('skills.edit'), icon: 'edit', run: () => emit('edit', skill) },
    { key: 'personal', label: t('skills.personal.assign'), icon: 'person', run: () => emit('personal', skill) },
  ] : []),
  { key: 'download', label: t('skills.download'), icon: 'download', run: () => emit('download', skill) },
  ...(canEdit ? [
    { key: 'toggle', label: t(skill.enabled ? 'skills.disableAll' : 'skills.enableAll'),
      icon: skill.enabled ? 'pause_circle' : 'play_circle', run: () => emit('toggle', skill) },
  ] : []),
  ...(canEdit && !skill.system ? [
    { key: 'delete', label: t('skills.delete'), icon: 'delete', negative: true, separator: true, run: () => emit('delete', skill) },
  ] : []),
])
function assign(category: number | null): void {
  if (canEdit) emit('category', skill, category)
}
</script>
