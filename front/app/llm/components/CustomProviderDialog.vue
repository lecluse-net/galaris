<template>
  <q-dialog v-model="open">
    <q-card class="custom-provider-dialog">
      <q-card-section class="galaris-dialog-title row items-center">
        <q-icon name="add_link" size="28px" class="q-mr-sm" />
        <div class="col">
          <div class="text-h6">{{ t('llm.addCustomProvider') }}</div>
          <div class="text-caption provider-dialog-subtitle">{{ t('llm.addCustomProviderHint') }}</div>
        </div>
        <q-btn flat round dense icon="close" :aria-label="$t('common.close')" class="text-white" @click="open = false" />
      </q-card-section>

      <q-separator />

      <q-form ref="customForm" @submit.prevent="submit">
        <q-card-section class="custom-provider-form">
          <div>
            <div class="text-caption text-weight-medium text-grey-7 q-mb-xs">
              {{ t('llm.providerType') }}
            </div>
            <q-btn-toggle
              v-model="form.provider_type"
              :options="typeOptions"
              spread
              no-caps
              unelevated
              toggle-color="primary"
              color="grey-2"
              text-color="grey-8"
              class="provider-type-toggle full-width"
              @update:model-value="onTypeChange"
            />
          </div>

          <q-banner rounded :class="providerHintClass">
            <template #avatar>
              <q-icon :name="selectedType.icon" />
            </template>
            {{ t(selectedType.hintKey) }}
          </q-banner>

          <q-input
            v-model="form.name"
            outlined
            autofocus
            :label="t('llm.providerName')"
            :rules="[value => Boolean(value?.trim()) || t('llm.nameRequired')]"
          >
            <template #prepend><q-icon name="badge" /></template>
          </q-input>

          <q-input
            v-model="form.base_url"
            outlined
            :label="t('llm.apiUrl')"
            :hint="t(selectedType.urlHintKey)"
            :rules="[value => Boolean(value?.trim()) || t('llm.apiUrlRequired')]"
          >
            <template #prepend><q-icon name="link" /></template>
          </q-input>

          <q-input
            v-model="form.api_key"
            outlined
            type="password"
            :label="t('llm.apiKey')"
            :hint="selectedType.apiKeyRequired ? t('llm.apiKeyPasteHint') : t('llm.apiKeyOptionalHint')"
            :rules="[apiKeyRule]"
            reactive-rules
            autocomplete="off"
          >
            <template #prepend><q-icon name="key" /></template>
          </q-input>

          <div class="provider-activation row items-center justify-between rounded-borders q-pa-md">
            <div class="col q-pr-md">
              <div class="text-weight-medium">{{ t('llm.providerEnabled') }}</div>
              <div class="text-caption text-grey-7">{{ t('llm.providerEnabledHint') }}</div>
            </div>
            <q-toggle v-model="form.is_active" color="positive" keep-color />
          </div>
        </q-card-section>

        <q-separator />

        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn flat :label="t('common.cancel')" @click="open = false" />
          <q-btn
            v-if="canEdit"
            type="submit"
            color="primary"
            icon="add"
            :label="t('common.create')"
            :loading="saving"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QForm } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type { LLMProviderCreate } from '../services/llmProviderService'
import {
  customProviderType,
  customProviderTypes,
} from '../customProviderTypes'

const open = defineModel<boolean>({ required: true })
const { saving = false } = defineProps<{ saving?: boolean }>()
const emit = defineEmits<{ create: [data: LLMProviderCreate] }>()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.LLM_PROVIDER_EDIT))
const customForm = useTemplateRef<QForm>('customForm')

const form = reactive({
  name: '',
  provider_type: 'openai_compatible',
  base_url: '',
  api_key: null as string | null,
  is_active: true,
})

const typeOptions = computed(() => customProviderTypes.map(item => ({
  label: t(item.labelKey),
  value: item.providerType,
  icon: item.icon,
})))
const selectedType = computed(() => customProviderType(form.provider_type))
const providerHintClass = computed(() => selectedType.value.bannerClass)

function apiKeyRule(value: string | null): true | string {
  if (!selectedType.value.apiKeyRequired || !form.is_active || value?.trim()) return true
  return t('llm.apiKeyRequired')
}

function reset(): void {
  form.name = ''
  form.provider_type = 'openai_compatible'
  form.base_url = ''
  form.api_key = null
  form.is_active = true
  customForm.value?.resetValidation()
}

function onTypeChange(value: string): void {
  const previousDefault = customProviderTypes.find(
    item => item.defaultBaseUrl === form.base_url,
  )
  const selected = customProviderType(value)
  if (!form.base_url || previousDefault) form.base_url = selected.defaultBaseUrl
}

async function submit(): Promise<void> {
  if (!canEdit.value) return
  if (!(await customForm.value?.validate())) return
  emit('create', {
    name: form.name.trim(),
    provider_type: form.provider_type,
    base_url: form.base_url.trim(),
    api_key: form.api_key || null,
    is_active: form.is_active,
  })
}

watch(open, value => {
  if (value) reset()
})
</script>

<style scoped>
.custom-provider-dialog {
  width: 680px;
  max-width: 94vw;
}

.provider-dialog-subtitle {
  color: rgba(255, 255, 255, 0.82);
}

.custom-provider-form {
  display: grid;
  gap: 18px;
  padding: 24px;
}

.provider-type-toggle {
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 4px;
  overflow: hidden;
}

.provider-type-toggle :deep(.q-btn) {
  min-height: 46px;
}

.provider-activation {
  background: rgba(0, 0, 0, 0.035);
  border: 1px solid rgba(0, 0, 0, 0.08);
}

body.body--dark .provider-type-toggle,
body.body--dark .provider-activation {
  border-color: rgba(255, 255, 255, 0.12);
}

body.body--dark .provider-activation {
  background: rgba(255, 255, 255, 0.05);
}

@media (max-width: 600px) {
  .custom-provider-form {
    padding: 16px;
  }

  .provider-type-toggle :deep(.q-btn) {
    min-height: 54px;
  }
}
</style>
