<template>
  <div class="toggle-examples">
    <section :aria-label="t('graphicReference.singleChoice')">
      <h3 class="text-subtitle1 q-mt-none q-mb-sm">{{ t('graphicReference.singleChoice') }}</h3>
      <q-btn-toggle
        v-model="view"
        :options="viewOptions"
        color="primary"
        text-color="primary"
        toggle-color="primary"
        toggle-text-color="white"
        no-caps
        unelevated
        :aria-label="t('graphicReference.singleChoice')"
      />
    </section>

    <section :aria-label="t('graphicReference.multipleChoices')">
      <h3 class="text-subtitle1 q-mt-none q-mb-sm">{{ t('graphicReference.multipleChoices') }}</h3>
      <q-btn-group unelevated role="group" :aria-label="t('graphicReference.multipleChoices')">
        <q-btn
          v-for="choice in formats"
          :key="choice.value"
          :icon="choice.icon"
          :aria-label="choice.label"
          :aria-pressed="formatting.includes(choice.value)"
          :outline="!formatting.includes(choice.value)"
          color="primary"
          @click="toggleFormat(choice.value)"
        >
          <q-tooltip>{{ choice.label }}</q-tooltip>
        </q-btn>
      </q-btn-group>
    </section>

    <section :aria-label="t('graphicReference.skillPolicies')">
      <h3 class="text-subtitle1 q-mt-none q-mb-sm">{{ t('graphicReference.skillPolicies') }}</h3>
      <div class="policy-examples">
        <div v-for="example in policies" :key="example.label">
          <div class="text-caption q-mb-xs">{{ t(`graphicReference.${example.label}`) }}</div>
          <SkillPolicyToggle
            v-model="example.value"
            :disable="example.disabled"
            :aria-label="t(`graphicReference.${example.label}`)"
          />
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { SkillPolicyToggle } from '@/graphicReferenceContributions'

const { t } = useI18n()
const view = ref('list')
const viewOptions = computed(() => [
  { value: 'list', icon: 'view_list', label: t('graphicReference.listView'), outline: view.value !== 'list' },
  { value: 'grid', icon: 'grid_view', label: t('graphicReference.gridView'), outline: view.value !== 'grid' },
  { value: 'tree', icon: 'account_tree', label: t('graphicReference.tree'), outline: view.value !== 'tree' },
])

type Format = 'bold' | 'italic' | 'underline'
const formatting = ref<Format[]>(['bold'])
const formats = computed(() => [
  { value: 'bold' as const, icon: 'format_bold', label: t('graphicReference.bold') },
  { value: 'italic' as const, icon: 'format_italic', label: t('graphicReference.italic') },
  { value: 'underline' as const, icon: 'format_underlined', label: t('graphicReference.underline') },
])
function toggleFormat(value: Format): void {
  formatting.value = formatting.value.includes(value)
    ? formatting.value.filter(selected => selected !== value)
    : [...formatting.value, value]
}

const policies = ref<{
  label: 'policyEnabled' | 'policyBlocked' | 'policyUnset' | 'disabled'
  value: 'enabled' | 'disabled' | null
  disabled: boolean
}[]>([
  { label: 'policyEnabled', value: 'enabled', disabled: false },
  { label: 'policyBlocked', value: 'disabled', disabled: false },
  { label: 'policyUnset', value: null, disabled: false },
  { label: 'disabled', value: 'enabled', disabled: true },
])
</script>

<style scoped>
.toggle-examples { display: flex; flex-wrap: wrap; gap: 24px 40px; }
.toggle-examples > section { min-width: 0; max-width: 100%; }
.policy-examples { display: flex; flex-wrap: wrap; gap: 16px 24px; }
</style>
