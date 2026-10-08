<template>
  <q-btn-group flat class="function-policy-toggle" role="group">
    <q-btn
      v-for="choice in choices"
      :key="choice.value"
      flat
      no-caps
      :disable="disable"
      class="function-policy-choice"
      :class="{ 'function-policy-selected': modelValue === choice.value, 'function-policy-yellow': choice.color === 'yellow' }"
      :style="{
        '--policy-accent': solaireCss[choice.color].accent,
        '--policy-light': solaireCss[choice.color].light,
        '--policy-dark': solaireCss[choice.color].dark,
      }"
      :aria-label="t(`connection.auth.${choice.label}`)"
      :aria-pressed="modelValue === choice.value"
      @click="emit('update:modelValue', choice.value)"
    >
      <q-icon v-if="choice.icon" :name="choice.icon" size="20px" />
      <span v-else class="function-policy-symbol" aria-hidden="true">{{ choice.symbol }}</span>
      <q-tooltip>{{ t(`connection.auth.${choice.tooltip}`) }}</q-tooltip>
    </q-btn>
  </q-btn-group>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { solaireCss, type SolaireColor } from '@/core/util'
import type { EffectiveFunctionState } from '../services/connectionService'

const { modelValue, disable = false } = defineProps<{
  modelValue: EffectiveFunctionState | null
  disable?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: EffectiveFunctionState] }>()
const { t } = useI18n()

interface PolicyChoice {
  value: EffectiveFunctionState
  color: SolaireColor
  label: string
  tooltip: string
  icon?: string
  symbol?: string
}

const choices: PolicyChoice[] = [
  { value: 'enabled', color: 'green', icon: 'check', label: 'stateEnabled', tooltip: 'allowTooltip' },
  { value: 'ask', color: 'yellow', symbol: '?', label: 'stateAsk', tooltip: 'askTooltip' },
  { value: 'disabled', color: 'red', icon: 'close', label: 'stateDisabled', tooltip: 'disableTooltip' },
]
</script>

<style scoped>
.function-policy-toggle { display: inline-flex; flex-wrap: nowrap; }
.function-policy-choice {
  min-width: 40px;
  min-height: 40px;
  padding: 8px;
  color: var(--policy-accent);
  background: var(--policy-light);
}
.function-policy-selected {
  color: #fff;
  background: var(--policy-accent);
  box-shadow: inset 0 -3px 0 rgba(0, 0, 0, .25);
}
.function-policy-symbol { font-size: 18px; font-weight: 700; line-height: 1; }
.function-policy-yellow { color: #101010; }
.function-policy-choice:focus-visible { outline: 2px solid var(--solaire-blue-accent); outline-offset: 2px; z-index: 1; }
body.body--dark .function-policy-choice:not(.function-policy-selected) { background: var(--policy-dark); }
body.body--dark .function-policy-yellow:not(.function-policy-selected) { color: var(--solaire-yellow-accent); }
</style>
