<template>
  <q-page v-if="contribution" class="harness-preferences q-pa-md">
    <PageHeader :icon="contribution.icon"
      :title="t('configuration.harnessProviderTitle', { name: contribution.label })"
      :description="t('harnessSettings.providerSubtitle', { name: contribution.label })"
    />

    <div v-if="paramsStore.loading && !paramsStore.params.length" class="row justify-center q-pa-lg">
      <q-spinner color="primary" size="3em" />
    </div>

    <q-card v-else flat bordered class="harness-preferences__content q-pa-lg">
      <BridgeSettingsPanel
        :key="contribution.kind"
        :contribution="contribution"
        organized
      />
    </q-card>
    <div class="q-mt-md">
      <q-btn flat color="primary" icon="arrow_back" :label="t('common.back')" to="/params/harnesses" />
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { PageHeader } from '@/core/util'
import { harnessBridgeSettings } from '../../bridgeSettings'
import BridgeSettingsPanel from '../../components/BridgeSettingsPanel.vue'
import { useParamsStore } from '../../stores/paramsStore'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const paramsStore = useParamsStore()
const availabilityResolved = ref(false)

const providerCode = computed(() => String(route.params.provider ?? ''))
const declaredContribution = computed(() => (
  harnessBridgeSettings.find(item => item.kind === providerCode.value)
))
const contribution = computed(() => {
  const item = declaredContribution.value
  if (!availabilityResolved.value || !item) return undefined
  return item.isAvailable?.() === false ? undefined : item
})

watch(providerCode, async () => {
  availabilityResolved.value = false
  const item = declaredContribution.value
  if (!item) {
    await router.replace('/params/harnesses')
    return
  }
  await item.refreshAvailability?.()
  if (item.isAvailable?.() === false) {
    await router.replace('/params/harnesses')
    return
  }
  availabilityResolved.value = true
  await paramsStore.fetchParams()
}, { immediate: true })
</script>

<style scoped>
.harness-preferences {
  min-width: 0;
}

.harness-preferences__content {
  max-width: 1280px;
}

@media (max-width: 599px) {
  .harness-preferences__content {
    padding: 16px;
  }
}
</style>
