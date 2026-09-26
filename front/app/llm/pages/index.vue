<template>
  <q-page class="llm-page q-pa-md" :class="{ 'viewport-page--desktop': activeTab === 'providers' && $q.screen.width >= 1280 }">
    <div class="llm-page-heading">
      <PageHeader help-key="models" :help-text="$t('contextHelpPages.models')" :icon="navigationIcon('smart_toy')" :title="t('nav.llm')" :description="t('nav.llm_desc')" />
    </div>

    <q-tabs
      v-model="activeTab"
      align="left"
      class="text-primary"
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab name="providers" icon="cloud" :label="t('llm.providerCatalog')" />
      <q-tab name="models" icon="smart_toy" :label="t('llm.myLlms')" />
      <q-tab v-if="canViewUsage" name="usage" icon="tune" :label="t('llm.usageTitle')" />
    </q-tabs>
    <q-separator />

    <q-tab-panels
      v-model="activeTab"
      animated
      keep-alive
      class="bg-transparent llm-tab-panels"
      @transition="onTabTransition"
    >
      <q-tab-panel name="providers" class="q-px-none provider-tab-panel">
        <ProviderWorkspace @create-llm="createLlmFromModel" />
      </q-tab-panel>

      <q-tab-panel name="models" class="q-px-none">
        <ConfiguredLlmManager ref="llmManager" :show-heading="false" />
      </q-tab-panel>

      <q-tab-panel v-if="canViewUsage" name="usage" class="q-px-none">
        <LlmUsageManager />
      </q-tab-panel>
    </q-tab-panels>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, ref, useTemplateRef, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { PageHeader } from '@/core/util'
import ConfiguredLlmManager from '../components/ConfiguredLlmManager.vue'
import LlmUsageManager from '../components/LlmUsageManager.vue'
import ProviderWorkspace from '../components/ProviderWorkspace.vue'
import type { LLMModelInfo } from '../services/llmProviderService'
import { privileges, usePrivilegeStore } from '@/core/authorize'

const { t } = useI18n()
const $q = useQuasar()
const route = useRoute()
const router = useRouter()
const privilegeStore = usePrivilegeStore()
const canViewUsage = computed(() => (
  privilegeStore.hasPrivilege(privileges.PARAMS_ACCESS)
  || privilegeStore.hasPrivilege(privileges.PARAMS_EDIT)
))
type LlmTab = 'providers' | 'models' | 'usage'
type LlmCreationRequest = { providerId: number; model: LLMModelInfo }

function tabFromQuery(value: unknown): LlmTab {
  if (value === 'usage' && !canViewUsage.value) return 'providers'
  return value === 'providers' || value === 'models' || value === 'usage'
    ? value
    : 'providers'
}

const activeTab = ref<LlmTab>(tabFromQuery(route.query.tab))
const llmManager = useTemplateRef<InstanceType<typeof ConfiguredLlmManager>>('llmManager')
const pendingLlmCreation = ref<LlmCreationRequest | null>(null)

watch(() => route.query.tab, value => {
  activeTab.value = tabFromQuery(value)
})

watch(canViewUsage, allowed => {
  if (!allowed && activeTab.value === 'usage') {
    activeTab.value = 'providers'
    return
  }
  if (allowed) activeTab.value = tabFromQuery(route.query.tab)
})

watch(activeTab, tab => {
  if (route.query.tab === tab) return
  void router.replace({ query: { ...route.query, tab } })
})

async function openPendingLlmCreation(): Promise<void> {
  const manager = llmManager.value
  const payload = pendingLlmCreation.value
  if (!manager || !payload) return

  pendingLlmCreation.value = null
  await manager.openForModel(payload.providerId, payload.model)
}

function onTabTransition(tab: string | number): void {
  if (tab === 'models') void openPendingLlmCreation()
}

function createLlmFromModel(payload: LlmCreationRequest): void {
  pendingLlmCreation.value = payload
  activeTab.value = 'models'
}
</script>

<style scoped>
@media (min-width: 1280px) {
  .viewport-page--desktop {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding-bottom: 0;
  }

  .viewport-page--desktop > :not(.llm-tab-panels) {
    flex-shrink: 0;
  }

  .viewport-page--desktop .llm-tab-panels {
    flex: 1;
    min-height: 0;
  }

  .viewport-page--desktop .llm-tab-panels :deep(.q-panel),
  .viewport-page--desktop .provider-tab-panel {
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .viewport-page--desktop .provider-tab-panel {
    padding-bottom: 0;
  }
}

@media (max-width: 1279px) {
  .llm-page {
    padding-right: 8px;
    padding-left: 8px;
  }
}
</style>
