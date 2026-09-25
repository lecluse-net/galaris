<template>
  <q-dialog v-model="open">
    <q-card class="synthetic-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6 col">{{ t('evaluation.synthetic.title') }}</div>
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section class="synthetic-fields">
        <p class="q-mb-none">{{ t('evaluation.synthetic.help') }}</p>
        <p class="q-mb-none">{{ t('evaluation.synthetic.focus.' + mechanism) }}</p>
        <template v-if="contextSource">
          <q-toggle v-model="useContext" :label="t('evaluation.synthetic.useContext', { name: contextSource.name })" :disable="busy" />
          <p v-if="useContext" class="q-mb-none">{{ t('evaluation.synthetic.contextHelp') }}</p>
          <p v-if="useContext && contextDirty && !busy" role="status">{{ t('evaluation.synthetic.saveContext') }}</p>
        </template>
        <p v-if="!contextSource || !useContext" class="q-mb-none">{{ t('evaluation.synthetic.freshContext') }}</p>
        <q-input v-model="name" outlined :label="t('evaluation.contract.name')" maxlength="300" :disable="busy" />
        <q-input v-model="instructions" outlined type="textarea" :rows="3" maxlength="6000" :label="t('evaluation.synthetic.instructions')" :disable="busy" />
        <q-select v-model="llmId" :options="models" option-value="id" option-label="label" emit-value map-options outlined :label="t('evaluation.synthetic.model')" :disable="busy" />
        <div class="row q-col-gutter-md">
          <q-input v-model.number="count" class="col-12 col-sm-6" outlined type="number" min="1" max="20" :label="t('evaluation.synthetic.count')" :disable="busy" />
          <q-select v-model="language" class="col-12 col-sm-6" outlined :options="languages" emit-value map-options :label="t('evaluation.synthetic.language')" :disable="busy" />
        </div>
        <q-select v-model="selectedCategories" multiple use-chips :options="categoryOptions" emit-value map-options outlined :label="t('evaluation.insights.categoryLabel')" :disable="busy" />
        <p>{{ t('evaluation.synthetic.review') }}</p>
        <div v-if="error" role="alert" class="text-negative">{{ error }}</div>
        <div v-if="busy" role="status">{{ t('evaluation.synthetic.generating') }}</div>
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn v-close-popup flat :label="t('common.close')" />
        <q-btn color="primary" icon="auto_awesome" :label="t('evaluation.synthetic.generate')" :loading="busy" :disable="!valid" @click="generate" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { categories, labWorkbenchService, type LabDataset, type LabKey } from '../services/labWorkbenchService'

const open = defineModel<boolean>({ required: true })
const { mechanism, models, defaultModel, sourceDataset, contextDirty = false } = defineProps<{
  mechanism: LabKey; models: Array<{ id: number; label: string }>; defaultModel: number | null
  sourceDataset?: Pick<LabDataset, 'id' | 'revision' | 'name'>; contextDirty?: boolean
}>()
const emit = defineEmits<{ generated: [dataset: LabDataset, cost: number, select: boolean] }>()
const { t, locale } = useI18n()
const name = ref(''), instructions = ref(''), count = ref<number | string>(8)
const language = ref<'en' | 'fr' | 'zh'>('fr')
const llmId = ref<number | null>(null), busy = ref(false), error = ref('')
const useContext = ref(Boolean(sourceDataset))
const pendingSource = ref<Pick<LabDataset, 'id' | 'revision' | 'name'> | null>(null)
const contextSource = computed(() => busy.value ? pendingSource.value : sourceDataset)
const selectedCategories = ref<string[]>(['nominal', 'ambiguity', 'incomplete'])
const languages = computed(() => ['fr', 'en', 'zh'].map(value => ({ value, label: t('evaluation.synthetic.languages.' + value) })))
const categoryOptions = computed(() => categories.map(value => ({ value, label: t('evaluation.insights.categories.' + value) })))
const valid = computed(() => name.value.trim() && llmId.value !== null && models.some(model => model.id === llmId.value)
  && !(useContext.value && sourceDataset && contextDirty)
  && Number.isInteger(count.value) && Number(count.value) >= Math.max(1, selectedCategories.value.length)
  && Number(count.value) <= 20 && selectedCategories.value.length > 0)
let request = 0
watch(open, value => {
  if (!value || busy.value) return
  error.value = ''
  llmId.value ??= defaultModel
  language.value = locale.value.startsWith('fr') ? 'fr' : locale.value.startsWith('zh') ? 'zh' : 'en'
}, { immediate: true })
watch(() => mechanism, () => {
  request++; open.value = false; busy.value = false
  name.value = ''; instructions.value = ''; error.value = ''; llmId.value = null
})
watch(() => sourceDataset?.id, () => {
  if (!busy.value) { useContext.value = Boolean(sourceDataset); error.value = '' }
})
onBeforeUnmount(() => { request++ })
async function generate() {
  if (!valid.value || busy.value) return
  const current = ++request, key = mechanism
  const source = useContext.value && sourceDataset ? { ...sourceDataset } : null
  pendingSource.value = source
  busy.value = true; error.value = ''
  try {
    const result = await labWorkbenchService.generateDataset(key, {
      name: name.value.trim(), instructions: instructions.value.trim(), count: Number(count.value),
      language: language.value, llm_id: llmId.value, categories: [...selectedCategories.value],
      ...(source ? { source_dataset_id: source.id, source_revision: source.revision } : {}),
    })
    if (current !== request || key !== mechanism) return
    emit('generated', result.dataset, result.cost, open.value && (!source || source.id === sourceDataset?.id))
    open.value = false; name.value = ''; instructions.value = ''
  } catch (reason) {
    if (current === request) error.value = apiErrorDetail(reason) ?? t('evaluation.synthetic.error')
  } finally { if (current === request) busy.value = false }
}
</script>

<style scoped>
.synthetic-dialog { width: 680px; max-width: 95vw; }
.synthetic-fields { display: flex; flex-direction: column; gap: 16px; }
</style>
