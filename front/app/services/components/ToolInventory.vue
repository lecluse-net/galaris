<template>
  <q-page class="tool-inventory q-pa-md">
    <PageHeader icon="fact_check" :title="t('toolInventory.title')" :description="t('toolInventory.description')">
      <template v-if="canRead" #actions>
        <q-btn outline color="primary" icon="refresh" :label="t('common.refresh')" :disable="loading"
          @click="loadInventory" />
      </template>
    </PageHeader>

    <div v-if="loading || privilegeStore.loading"
      class="row items-center q-gutter-sm q-py-lg" role="status">
      <q-spinner color="primary" />
      <span>{{ t('toolInventory.loading') }}</span>
    </div>
    <q-banner v-else-if="!canRead" role="status">{{ t('toolInventory.noAccess') }}</q-banner>
    <q-banner v-else-if="loadFailed" role="alert">
      {{ t('toolInventory.loadFailed') }}
      <template #action>
        <q-btn outline color="primary" :label="t('common.retry')" @click="loadInventory" />
      </template>
    </q-banner>
    <template v-else>
      <div class="inventory-toolbar q-my-md">
        <q-input v-model="search" outlined dense clearable type="search" :label="t('toolInventory.search')">
          <template #prepend><q-icon name="search" aria-hidden="true" /></template>
        </q-input>
        <div class="row items-center q-gutter-sm" aria-live="polite">
          <StatusBadge tone="active" :label="t('toolInventory.serviceCount', visibleServices.length)" />
          <StatusBadge tone="neutral" :label="t('toolInventory.toolCount', toolCount)" />
          <StatusBadge tone="success" :label="t('toolInventory.openCount', openCount)" />
        </div>
      </div>
      <p class="q-mb-md">{{ t('toolInventory.policyScope') }}</p>

      <q-banner v-if="!visibleServices.length" rounded role="status">
        {{ t(query ? 'toolInventory.noMatches' : 'toolInventory.empty') }}
      </q-banner>
      <q-card v-for="{ service, label, tools } in visibleServices" :key="service.code" flat bordered class="q-mb-sm">
        <q-expansion-item :label="label"
          :model-value="expanded[service.code] ?? (Boolean(query) || service.code === 'galaris')"
          @update:model-value="value => expanded[service.code] = value">
          <template #header>
            <q-item-section avatar>
              <ServiceIdentityIcon :service="{ code: service.code, icon: service.icon, can_edit: false }" :size="26" />
            </q-item-section>
            <q-item-section class="inventory-service">
              <q-item-label><strong>{{ label }}</strong></q-item-label>
              <q-item-label caption><code>{{ service.code }}</code></q-item-label>
              <q-item-label v-if="scopeDefault(service)" caption>
                {{ t('toolInventory.defaultScope', { value: scopeDefault(service) }) }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>{{ t('toolInventory.toolCount', tools.length) }}</q-item-section>
          </template>
          <template v-if="expanded[service.code] !== undefined || query || service.code === 'galaris'">
            <q-separator />
            <ConnectionDefaults :service="service" />
            <q-separator />
            <ToolInventoryTable v-if="tools.length" :tools="tools" :service-label="label" />
            <div v-else class="q-pa-md">
              {{ t('toolInventory.noTools') }}
            </div>
          </template>
        </q-expansion-item>
      </q-card>
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { PageHeader, StatusBadge } from '@/core/util'
import ConnectionDefaults from './ConnectionDefaults.vue'
import ServiceIdentityIcon from './ServiceIdentityIcon.vue'
import ToolInventoryTable from './ToolInventoryTable.vue'
import { toolMessageKey } from '../presentation'
import serviceApi, { type ServiceToolInventory } from '../services/serviceApi'

const { t, te, locale } = useI18n()
const privilegeStore = usePrivilegeStore()
const canRead = computed(() => privilegeStore.hasAnyPrivilege([privileges.SERVICE_ACCESS, privileges.SERVICE_EDIT]))
const services = shallowRef<ServiceToolInventory[]>([])
const expanded = ref<Record<string, boolean>>({})
const search = ref<string | null>('')
const query = computed(() => search.value?.trim().toLocaleLowerCase(locale.value) ?? '')
const loading = ref(false)
const loadFailed = ref(false)
let inventoryRequest: AbortController | undefined

const visibleServices = computed(() => {
  const collator = new Intl.Collator(locale.value)
  return services.value.map(service => {
    const key = toolMessageKey(service.code, 'label')
    return { service, label: key && te(key) ? t(key) : service.label }
  }).sort((a, b) => collator.compare(a.label, b.label)).flatMap(({ service, label }) => {
    const matchesService = [label, service.label, service.code]
      .some(value => value.toLocaleLowerCase(locale.value).includes(query.value))
    if (matchesService) return [{ service, label, tools: service.tools }]
    const matches = service.tools.filter(tool => tool.name.toLocaleLowerCase(locale.value).includes(query.value))
    return matches.length ? [{ service, label, tools: matches }] : []
  })
})
const toolCount = computed(() => visibleServices.value.reduce((total, { tools }) => total + tools.length, 0))
const openCount = computed(() => visibleServices.value.reduce((total, { tools }) => (
  total + tools.filter(tool => tool.conversation_enabled).length
), 0))

function scopeDefault(service: ServiceToolInventory): string {
  const value = service.connection_schema.params['services.management_scope']?.default
  if (!value) return ''
  const key = `toolInventory.scopes.${value}`
  return te(key) ? t(key) : value
}

async function loadInventory(): Promise<void> {
  inventoryRequest?.abort()
  services.value = []
  loadFailed.value = false
  loading.value = canRead.value
  if (!canRead.value) return
  const request = inventoryRequest = new AbortController()
  try {
    const { data } = await serviceApi.getToolInventory(request.signal)
    if (!request.signal.aborted) services.value = data
  } catch {
    if (!request.signal.aborted) loadFailed.value = true
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}

watch(canRead, loadInventory, { immediate: true })
watch(query, () => { expanded.value = {} })
onScopeDispose(() => inventoryRequest?.abort())
</script>

<style scoped>
.tool-inventory {
  padding-top: 24px;
}

@media (min-width: 1024px) {
  .tool-inventory {
    padding-top: 72px;
  }
}

.inventory-toolbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px 24px;
}

.inventory-toolbar .q-field {
  flex: 1 1 300px;
  max-width: 520px;
}

.inventory-service {
  overflow-wrap: anywhere;
}
</style>
