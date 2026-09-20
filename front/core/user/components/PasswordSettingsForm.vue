<template>
  <div>
    <div class="row items-center q-gutter-sm">
      <q-icon name="password" color="primary" size="sm" />
      <div class="text-subtitle1 text-weight-medium">{{ t('userEdit.passwordTitle') }}</div>
    </div>
    <div class="text-caption text-grey-7 q-mt-xs">
      {{ t('userEdit.passwordDescription') }}
    </div>

    <q-form class="password-fields q-mt-sm" @submit.prevent="submitPassword">
      <q-input
        v-model="password"
        :label="t('userEdit.newPassword')"
        :type="showPassword ? 'text' : 'password'"
        outlined
        dense
        maxlength="72"
        autocomplete="new-password"
        :rules="[
          value => !!value || t('auth.passwordRequired'),
          value => value.length >= 12 || t('userEdit.passwordMin'),
        ]"
      >
        <template #prepend>
          <q-icon name="lock" />
        </template>
        <template #append>
          <q-btn
            flat
            round
            dense
            :icon="showPassword ? 'visibility_off' : 'visibility'"
            :aria-label="t('userEdit.togglePasswordVisibility')"
            @click="showPassword = !showPassword"
          />
        </template>
      </q-input>

      <q-input
        v-model="passwordConfirmation"
        :label="t('auth.confirmPassword')"
        :type="showPassword ? 'text' : 'password'"
        outlined
        dense
        maxlength="72"
        autocomplete="new-password"
        :rules="[
          value => !!value || t('auth.confirmRequired'),
          value => value === password || t('auth.passwordMismatch'),
        ]"
      >
        <template #prepend>
          <q-icon name="lock_reset" />
        </template>
      </q-input>

      <div class="password-actions row justify-end">
        <q-btn
          type="submit"
          color="primary"
          no-caps
          icon="key"
          :label="t('userEdit.updatePassword')"
          :loading="loading"
        />
      </div>
    </q-form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { loading = false } = defineProps<{
  loading?: boolean
}>()
const emit = defineEmits<{
  update: [password: string]
}>()

const { t } = useI18n()
const password = ref('')
const passwordConfirmation = ref('')
const showPassword = ref(false)

function submitPassword(): void {
  if (!password.value || password.value !== passwordConfirmation.value) return
  emit('update', password.value)
  password.value = ''
  passwordConfirmation.value = ''
}
</script>

<style scoped>
.password-fields {
  display: grid;
  gap: 8px 12px;
}

@media (min-width: 1024px) {
  .password-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .password-actions { grid-column: 1 / -1; }
}
</style>
