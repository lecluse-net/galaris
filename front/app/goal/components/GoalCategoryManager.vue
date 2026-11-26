<template>
  <q-card flat bordered>
    <q-card-section>
      <p class="text-grey-7">{{ t('goal.categories.private') }}</p>
      <q-form class="row q-col-gutter-sm items-start" @submit="createCategory">
        <div class="col-12 col-sm">
          <q-input v-model="newLabel" outlined dense maxlength="200" :label="t('goal.categories.new')" :disable="busy" />
        </div>
        <div class="col-12 col-sm-auto">
          <q-btn type="submit" color="primary" icon="add" :label="t('goal.categories.add')" :disable="busy || !newLabel.trim()" />
        </div>
      </q-form>
    </q-card-section>
    <q-banner v-if="error" class="q-mx-md q-mb-md" role="alert">
      {{ error }}
      <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="load" /></template>
    </q-banner>
    <q-card-section v-if="loading" class="text-center"><q-spinner color="primary" /></q-card-section>
    <q-list v-else-if="categories.length" separator>
      <q-item v-for="category in categories" :key="category.id">
        <q-item-section>
          <q-input v-model="drafts[category.id]" outlined dense maxlength="200" :aria-label="t('goal.categories.label')" :disable="busy" @keydown.enter.prevent="save(category)" />
        </q-item-section>
        <q-item-section side>
          <div class="row no-wrap">
            <q-btn flat round color="primary" icon="save" :aria-label="t('common.save')" :disable="busy || !drafts[category.id]?.trim() || drafts[category.id]?.trim() === category.label" @click="save(category)" />
            <q-btn flat round color="negative" icon="delete" :aria-label="t('goal.delete')" :disable="busy" @click="confirmDelete(category)" />
          </div>
        </q-item-section>
      </q-item>
    </q-list>
    <q-card-section v-else-if="!error" class="text-grey-7 text-center">{{ t('goal.categories.empty') }}</q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail, sessionGeneration } from '@/core/api'
import { showConfirmationDialog } from '@/core/util'
import { categoryService } from '../services/categoryService'
import type { GoalCategory } from '../types'

const { active } = defineProps<{ active: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const categories = ref<GoalCategory[]>([])
const drafts = reactive<Record<number, string>>({})
const newLabel = ref('')
const loading = ref(false)
const busy = ref(false)
const error = ref('')
let generation = 0

watch(() => active, visible => {
  if (visible && !busy.value) void load()
}, { immediate: true })
onBeforeUnmount(() => { generation++ })

async function load(): Promise<void> {
  const request = ++generation, session = sessionGeneration()
  loading.value = true
  error.value = ''
  try {
    const result = await categoryService.list()
    if (request !== generation || session !== sessionGeneration()) return
    categories.value = result
    for (const key of Object.keys(drafts)) delete drafts[Number(key)]
    for (const category of result) drafts[category.id] = category.label
  } catch (caught) {
    if (request === generation && session === sessionGeneration()) error.value = apiErrorDetail(caught) || t('goal.categories.error')
  } finally {
    if (request === generation) loading.value = false
  }
}

async function mutate(action: () => Promise<unknown>): Promise<void> {
  if (busy.value) return
  const request = generation, session = sessionGeneration()
  busy.value = true
  error.value = ''
  try {
    await action()
    if (session !== sessionGeneration()) return
    emit('changed')
    if (request === generation) { newLabel.value = ''; await load() }
  } catch (caught) {
    if (request === generation && session === sessionGeneration()) error.value = apiErrorDetail(caught) || t('goal.categories.error')
  } finally {
    busy.value = false
  }
}

function createCategory(): void {
  const label = newLabel.value.trim()
  if (label) void mutate(() => categoryService.create(label))
}
function save(category: GoalCategory): void {
  const label = drafts[category.id]?.trim()
  if (label && label !== category.label) void mutate(() => categoryService.update(category.id, label))
}
function confirmDelete(category: GoalCategory): void {
  showConfirmationDialog({ title: t('goal.categories.deleteTitle'), message: t('goal.categories.deleteConfirm', { label: category.label }), ok: t('goal.delete'), cancel: t('common.cancel'), color: 'negative' })
    .onOk(() => { void mutate(() => categoryService.delete(category.id)) })
}
</script>
