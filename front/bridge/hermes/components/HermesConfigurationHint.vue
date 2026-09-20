<template>
  <q-banner rounded class="hermes-configuration-hint q-mb-lg">
    <template #avatar><q-icon name="info_outline" /></template>
    {{ t('hermes.agentSettingsHint') }}
  </q-banner>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
</script>

<style scoped>
.hermes-configuration-hint { background: var(--solaire-blue-light); }
.body--dark .hermes-configuration-hint { background: var(--solaire-blue-dark); }
</style>
