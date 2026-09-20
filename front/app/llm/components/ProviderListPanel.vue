<template>
  <section class="provider-list-panel column no-wrap">
    <div class="row items-center justify-between q-pa-md provider-panel-header">
      <div>
        <div class="text-subtitle1 text-weight-bold">{{ t('llm.providerCatalog') }}</div>
        <div class="text-caption text-grey-7">{{ t('llm.providerCatalogHint') }}</div>
      </div>
    </div>

    <component
      :is="$q.screen.width < 1280 ? 'div' : QScrollArea"
      v-bind="$q.screen.width < 1280 ? {} : { visible: true, thumbStyle: { width: '8px', backgroundColor: 'var(--q-primary)', opacity: '0.65' } }"
      class="col provider-list-scroll"
    >
      <div class="q-pa-sm">
        <div class="provider-group-title row items-center q-px-sm q-py-xs">
          <q-icon name="check_circle" color="positive" size="16px" class="q-mr-xs" />
          <span>{{ t('llm.activeProviders') }}</span>
          <q-badge color="positive" rounded class="q-ml-sm">{{ activeItems.length }}</q-badge>
        </div>

        <q-list v-if="activeItems.length" padding class="q-mb-md">
          <q-item
            v-for="item in activeItems"
            :key="item.key"
            clickable
            v-ripple
            :active="selectedKey === item.key"
            active-class="provider-item--active"
            class="provider-item rounded-borders q-mb-xs"
            @click="emit('select', item.key)"
          >
            <q-item-section avatar>
              <ProviderAvatar :item="item" />
            </q-item-section>
            <q-item-section>
              <q-item-label class="text-weight-medium">{{ item.display_name }}</q-item-label>
              <q-item-label caption lines="1">
                {{ item.is_custom ? customTypeLabel(item) : authLabel(item) }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-icon
                v-if="item.auth_type === 'oauth_device'"
                :name="item.connection?.oauth_connected ? 'verified_user' : 'warning'"
                :color="item.connection?.oauth_connected ? 'positive' : 'warning'"
                size="18px"
              />
              <q-icon v-else name="fiber_manual_record" color="positive" size="12px" />
            </q-item-section>
          </q-item>
        </q-list>
        <div v-else class="text-caption text-grey-6 q-pa-sm q-mb-md">
          {{ t('llm.noActiveProvider') }}
        </div>

        <div class="provider-group-title row items-center q-px-sm q-py-xs">
          <q-icon name="add_circle_outline" color="grey-7" size="16px" class="q-mr-xs" />
          <span>{{ t('llm.availableProviders') }}</span>
          <q-badge color="grey-7" rounded class="q-ml-sm">{{ availableItems.length }}</q-badge>
        </div>

        <q-list padding>
          <div v-if="canEdit" class="q-px-md q-pb-sm">
            <q-btn
              outline
              dense
              padding="2px 6px"
              color="primary"
              no-caps
              class="full-width bg-white provider-add-button"
              @click="emit('add')"
            >
              <span class="provider-add-button__content">
                <q-icon name="add" size="20px" aria-hidden="true" />
                <span class="provider-add-button__label">{{ t('llm.newCustomProvider') }}</span>
              </span>
            </q-btn>
          </div>
          <q-item
            v-for="item in availableItems"
            :key="item.key"
            clickable
            v-ripple
            :active="selectedKey === item.key"
            active-class="provider-item--active"
            class="provider-item rounded-borders q-mb-xs"
            @click="emit('select', item.key)"
          >
            <q-item-section avatar>
              <ProviderAvatar :item="item" />
            </q-item-section>
            <q-item-section>
              <q-item-label class="text-weight-medium">{{ item.display_name }}</q-item-label>
              <q-item-label caption lines="1">
                {{ item.is_custom ? customTypeLabel(item) : authLabel(item) }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-icon name="chevron_right" color="grey-6" />
            </q-item-section>
          </q-item>
        </q-list>
      </div>
    </component>

    <q-inner-loading :showing="loading">
      <q-spinner color="primary" size="28px" />
    </q-inner-loading>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { QScrollArea, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type { ProviderCatalogItem } from '../services/llmProviderService'
import { customProviderType } from '../customProviderTypes'
import ProviderAvatar from './ProviderAvatar.vue'

const props = defineProps<{
  items: ProviderCatalogItem[]
  selectedKey: string | null
  loading?: boolean
}>()

const emit = defineEmits<{
  select: [key: string]
  add: []
}>()

const { t, locale } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.LLM_PROVIDER_EDIT))

const sortedItems = computed(() => [...props.items].sort((a, b) =>
  a.display_name.localeCompare(b.display_name, locale.value, { sensitivity: 'base', numeric: true }),
))
const activeItems = computed(() => sortedItems.value.filter(item => item.connection?.is_active))
const availableItems = computed(() => sortedItems.value.filter(item => !item.connection?.is_active))

function authLabel(item: ProviderCatalogItem): string {
  if (item.auth_type === 'oauth_device') return t('llm.authSubscription')
  if (item.auth_type === 'optional_api_key') return t('llm.authOptionalToken')
  return t('llm.authApiKey')
}

function customTypeLabel(item: ProviderCatalogItem): string {
  return t(customProviderType(item.provider_type).labelKey)
}
</script>

<style scoped>
.provider-add-button {
  min-height: 28px;
}

.provider-add-button__content {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
}

.provider-add-button__content > .q-icon {
  flex-shrink: 0;
}

.provider-add-button__label {
  flex: 1;
  min-width: 0;
  line-height: 1.15;
  text-align: left;
  white-space: normal;
  overflow-wrap: anywhere;
}

.provider-list-panel {
  min-height: 640px;
  position: relative;
  background: color-mix(in srgb, var(--q-primary) 2%, transparent);
}

.provider-list-scroll {
  min-height: 0;
  overflow-y: auto;
}

.provider-panel-header {
  min-height: 74px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

body.body--dark .provider-panel-header {
  border-bottom-color: rgba(255, 255, 255, 0.1);
}

body.body--dark .provider-group-title {
  color: rgba(255, 255, 255, 0.62);
}

.provider-group-title {
  color: rgba(0, 0, 0, 0.62);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.provider-item {
  min-height: 54px;
  transition: background-color 120ms ease, box-shadow 120ms ease;
}

.provider-item--active {
  color: var(--q-primary);
  background: color-mix(in srgb, var(--q-primary) 11%, transparent);
  box-shadow: inset 3px 0 0 var(--q-primary);
}

body.body--dark .provider-panel-header {
  border-bottom-color: rgba(255, 255, 255, 0.12);
}

body.body--dark .provider-group-title {
  color: rgba(255, 255, 255, 0.62);
}

@media (min-width: 1280px) {
  .provider-list-panel {
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .provider-panel-header {
    flex-shrink: 0;
  }

  .provider-list-scroll {
    overflow: hidden;
  }
}

@media (max-width: 1279px) {
  .provider-list-panel {
    min-height: 0;
  }

  .provider-list-scroll {
    flex: none;
    overflow: visible;
  }
}
</style>
