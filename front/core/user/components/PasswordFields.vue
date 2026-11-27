<template>
  <div class="password-pair" :class="{ 'password-pair--stacked': stacked }">
    <q-input
      v-model="password"
      :label="t(labelKey)"
      :type="visible ? 'text' : 'password'"
      :hint="t(password ? feedbackKey : optional ? 'userAdmin.passwordKeep' : 'passwordPolicy.guidance')"
      :rules="[validatePassword]"
      autocomplete="new-password"
      outlined dense hide-bottom-space
    >
      <template #append>
        <q-btn
          flat round dense color="primary"
          :icon="visible ? 'visibility_off' : 'visibility'"
          :aria-label="t(visible ? 'userAdmin.hidePassword' : 'userAdmin.showPassword')"
          @click="visible = !visible"
        />
      </template>
    </q-input>
    <q-input
      v-model="confirmation"
      :label="t('auth.confirmPassword')"
      :type="visible ? 'text' : 'password'"
      :rules="confirmationRules"
      reactive-rules lazy-rules
      autocomplete="new-password"
      outlined dense hide-bottom-space
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const { optional = false, labelKey = 'auth.password', stacked = false } = defineProps<{
  optional?: boolean
  labelKey?: string
  stacked?: boolean
}>()
const password = defineModel<string>({ required: true })
const confirmation = defineModel<string>('confirmation', { default: '' })
const visible = ref(false)
const { t } = useI18n()

const feedbackKey = computed(() => {
  const value = password.value
  const characters = Array.from(value)
  if (characters.length < 12) return 'auth.passwordMinChars'
  if (new TextEncoder().encode(value).length > 72) return 'passwordPolicy.tooLong'
  const compact = value.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '')
  if (
    new Set(value.trim()).size < 4 ||
    /^(.{1,4})\1+$/su.test(value.toLowerCase()) ||
    /^(?:password|passw0rd|motdepasse|qwerty|azerty|letmein|admin)[0-9]*$/.test(compact) ||
    (compact && ('012345678901234567890123456789'.includes(compact) || 'abcdefghijklmnopqrstuvwxyz'.includes(compact)))
  ) return 'passwordPolicy.predictable'
  return 'passwordPolicy.acceptable'
})

function validatePassword(value: string): true | string {
  if (!value) return optional || t('auth.passwordRequired')
  return feedbackKey.value === 'passwordPolicy.acceptable' || t(feedbackKey.value)
}

const confirmationRules = computed(() => {
  const expected = password.value
  return [(value: string) => {
    if (optional && !expected && !value) return true
    if (!value) return t('auth.confirmRequired')
    return value === expected || t('auth.passwordMismatch')
  }]
})

watch(password, value => {
  if (!value) confirmation.value = ''
})
</script>

<style scoped>
.password-pair {
  display: grid;
  gap: 8px 12px;
}

@media (min-width: 1024px) {
  .password-pair:not(.password-pair--stacked) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
