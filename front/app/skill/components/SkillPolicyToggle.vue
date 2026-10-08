<template>
  <q-btn-group flat class="skill-policy-toggle" role="group">
    <q-btn
      v-for="choice in choices"
      :key="choice.value"
      flat
      no-caps
      :disable="disable"
      class="skill-policy-choice"
      :class="{ 'skill-policy-selected': modelValue === choice.value }"
      :style="{
        '--policy-accent': solaireCss[choice.color].accent,
        '--policy-light': solaireCss[choice.color].light,
        '--policy-dark': solaireCss[choice.color].dark,
      }"
      :aria-label="choice.label"
      :aria-pressed="modelValue === choice.value"
      @click="selectPolicy(choice.value)"
    >
      <q-icon :name="choice.icon" size="20px" />
      <q-tooltip>{{ choice.label }}</q-tooltip>
    </q-btn>
  </q-btn-group>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { solaireCss, type SolaireColor } from '@/core/util'
import type { SkillGlobalAuthorizationState } from '../services/skillService'

const { modelValue, disable = false } = defineProps<{
  modelValue: SkillGlobalAuthorizationState | null
  disable?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: SkillGlobalAuthorizationState] }>()
const { t } = useI18n()

function selectPolicy(value: SkillGlobalAuthorizationState): void {
  if (value !== modelValue) emit('update:modelValue', value)
}

const choices = computed<{
  value: SkillGlobalAuthorizationState
  color: SolaireColor
  icon: string
  label: string
}[]>(() => [
  { value: 'enabled', color: 'green', icon: 'check', label: t('skills.auth.stateEnabled') },
  { value: 'disabled', color: 'red', icon: 'close', label: t('skills.auth.stateDisabled') },
])
</script>

<style scoped>
.skill-policy-toggle { display: inline-flex; flex-wrap: nowrap; }
.skill-policy-choice {
  min-width: 40px;
  min-height: 40px;
  padding: 8px;
  color: var(--policy-accent);
  background: var(--policy-light);
}
.skill-policy-selected {
  color: #fff;
  background: var(--policy-accent);
  box-shadow: inset 0 -3px 0 rgba(0, 0, 0, .25);
}
.skill-policy-choice:focus-visible { outline: 2px solid var(--solaire-blue-accent); outline-offset: 2px; z-index: 1; }
body.body--dark .skill-policy-choice:not(.skill-policy-selected) { background: var(--policy-dark); }
</style>
