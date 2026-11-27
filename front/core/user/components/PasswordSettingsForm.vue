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
      <PasswordFields v-model="password" label-key="userEdit.newPassword" />

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
import PasswordFields from './PasswordFields.vue'

const { loading = false } = defineProps<{
  loading?: boolean
}>()
const emit = defineEmits<{
  update: [password: string]
}>()

const { t } = useI18n()
const password = ref('')

function submitPassword(): void {
  if (loading || !password.value) return
  emit('update', password.value)
  password.value = ''
}
</script>

<style scoped>
.password-fields {
  display: grid;
  gap: 8px 12px;
}
</style>
