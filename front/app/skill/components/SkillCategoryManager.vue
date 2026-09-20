<template>
  <q-dialog v-model="open">
    <q-card class="category-dialog">
      <q-toolbar class="galaris-dialog-title bg-primary text-white">
        <q-toolbar-title>{{ t('skills.categories.manageTitle') }}</q-toolbar-title>
        <q-btn
          v-close-popup
          flat
          round
          dense
          icon="close"
          :aria-label="t('skills.cancel')"
        />
      </q-toolbar>

      <q-card-section>
        <div class="row q-col-gutter-sm items-start">
          <div class="col">
            <q-input
              v-model="newLabel"
              outlined
              dense
              :label="t('skills.categories.newLabel')"
              @keydown.enter.prevent="createCategory"
            />
          </div>
          <div class="col-auto">
            <q-btn
              color="primary"
              icon="add"
              :label="t('skills.categories.create')"
              :disable="!newLabel.trim()"
              @click="createCategory"
            />
          </div>
        </div>
      </q-card-section>

      <q-separator />

      <q-list v-if="store.categories.length" separator class="category-list scroll">
        <q-item v-for="category in store.categories" :key="category.id">
          <q-item-section>
            <q-input
              v-model="draftLabels[category.id]"
              dense
              borderless
              :aria-label="t('skills.categories.label')"
              @keydown.enter.prevent="saveCategory(category)"
            />
            <q-item-label caption>
              {{ t('skills.categories.skillCount', { count: category.skill_count }) }}
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="row no-wrap q-gutter-xs">
              <q-btn
                flat
                round
                color="primary"
                icon="save"
                :disable="!canSave(category)"
                @click="saveCategory(category)"
              >
                <q-tooltip>{{ t('skills.save') }}</q-tooltip>
              </q-btn>
              <q-btn
                flat
                round
                color="negative"
                icon="delete"
                @click="categoryToDelete = category"
              >
                <q-tooltip>{{ t('skills.delete') }}</q-tooltip>
              </q-btn>
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <q-card-section v-else class="text-grey-7 text-center">
        {{ t('skills.categories.empty') }}
      </q-card-section>

      <q-separator />
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn flat :label="t('skills.categories.close')" v-close-popup />
      </q-card-actions>
    </q-card>
  </q-dialog>

  <q-dialog :model-value="categoryToDelete !== null" @hide="categoryToDelete = null">
    <q-card style="width: 520px; max-width: 95vw">
      <q-toolbar class="galaris-dialog-title bg-primary text-white">
        <q-toolbar-title>{{ t('skills.categories.deleteTitle') }}</q-toolbar-title>
        <q-btn
          v-close-popup
          flat
          round
          dense
          icon="close"
          :aria-label="t('skills.cancel')"
        />
      </q-toolbar>
      <q-card-section>
        {{ t('skills.categories.deleteConfirm', { label: categoryToDelete?.label || '' }) }}
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn flat :label="t('skills.cancel')" v-close-popup />
        <q-btn
          color="negative"
          :label="t('skills.delete')"
          @click="deleteCategory"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'

import type { SkillCategory } from '../services/skillService'
import { useSkillStore } from '../stores/skillStore'

const open = defineModel<boolean>({ default: false })
const $q = useQuasar()
const { t } = useI18n()
const store = useSkillStore()
const newLabel = ref('')
const draftLabels = reactive<Record<number, string>>({})
const categoryToDelete = ref<SkillCategory | null>(null)

watch(
  () => store.categories,
  categories => {
    for (const key of Object.keys(draftLabels)) delete draftLabels[Number(key)]
    for (const category of categories) draftLabels[category.id] = category.label
  },
  { deep: true, immediate: true },
)

function canSave(category: SkillCategory): boolean {
  const label = draftLabels[category.id]?.trim() || ''
  return Boolean(label) && label !== category.label
}

async function createCategory(): Promise<void> {
  const label = newLabel.value.trim()
  if (!label) return
  try {
    await store.createCategory(label)
    newLabel.value = ''
    $q.notify({ type: 'positive', message: t('skills.categories.created') })
  } catch (error) {
    console.error('Error creating skill category:', error)
    $q.notify({ type: 'negative', message: t('skills.categories.error') })
  }
}

async function saveCategory(category: SkillCategory): Promise<void> {
  const label = draftLabels[category.id]?.trim() || ''
  if (!label || label === category.label) return
  try {
    await store.updateCategory(category.id, label)
    $q.notify({ type: 'positive', message: t('skills.categories.updated') })
  } catch (error) {
    console.error('Error updating skill category:', error)
    draftLabels[category.id] = category.label
    $q.notify({ type: 'negative', message: t('skills.categories.error') })
  }
}

async function deleteCategory(): Promise<void> {
  if (!categoryToDelete.value) return
  try {
    await store.deleteCategory(categoryToDelete.value.id)
    categoryToDelete.value = null
    $q.notify({ type: 'positive', message: t('skills.categories.deleted') })
  } catch (error) {
    console.error('Error deleting skill category:', error)
    $q.notify({ type: 'negative', message: t('skills.categories.error') })
  }
}
</script>

<style scoped>
.category-dialog {
  width: 680px;
  max-width: 95vw;
}

.category-list {
  max-height: 55vh;
}
</style>
