<template>
  <q-markup-table flat dense class="connection-defaults">
    <thead>
      <tr>
        <th scope="col">
          {{ t('toolInventory.connectionParameters') }}
          <div class="text-caption">{{ t(`toolInventory.connectionDefaults.${service.connection_default}`) }}</div>
        </th>
        <th scope="col">{{ t('toolInventory.softwareDefault') }}</th>
        <th scope="col">{{ t('toolInventory.inheritedValue') }}</th>
      </tr>
    </thead>
    <tbody>
      <tr v-if="!parameters.length">
        <td colspan="3">{{ t('toolInventory.noParameters') }}</td>
      </tr>
      <tr v-for="{ name, label, defaultValue, inheritedValue, forced, scopeOptions } in parameters" :key="name">
        <th scope="row">
          <div>{{ label }}</div>
          <code v-if="name !== label" class="text-caption">{{ name }}</code>
          <div v-if="scopeOptions" class="text-caption q-mt-xs">
            {{ t('toolInventory.scopeOptions', { options: scopeOptions }) }}
          </div>
        </th>
        <td>{{ defaultValue }}</td>
        <td>
          {{ inheritedValue }}
          <div v-if="forced" class="text-caption">{{ t('toolInventory.enforced') }}</div>
        </td>
      </tr>
    </tbody>
  </q-markup-table>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { connectionParamLabel, connectionParamOptions, sortedConnectionParamEntries } from '../presentation'
import type { ServiceToolInventory } from '../services/serviceApi'

const { service } = defineProps<{ service: ServiceToolInventory }>()
const { t, te } = useI18n()
const parameters = computed(() => sortedConnectionParamEntries(service.connection_schema.params).map(([name, definition]) => {
  const options = connectionParamOptions(service.code, name, definition, t, te)
  const global = service.global_params[name]
  const scope = name === 'services.management_scope'
  const displayValue = (value: string): string => options.find(option => option.value === value)?.label ?? value
  const defaultValue = definition.default && definition.type !== 'password'
    ? displayValue(definition.default)
    : t(definition.required ? 'toolInventory.requiredValue' : 'toolInventory.noValue')
  const inheritedValue = global?.configured
    ? global.secret ? t('services.secretConfigured') : displayValue(global.value ?? '')
    : t(scope ? 'toolInventory.connectionOnly' : 'toolInventory.noValue')
  return {
    name, defaultValue, inheritedValue,
    label: connectionParamLabel(service.code, name, definition, t, te),
    forced: global?.forced ?? false,
    scopeOptions: scope ? options.map(option => option.label).join(' · ') : '',
  }
}))
</script>

<style scoped>
.connection-defaults :deep(table) {
  table-layout: fixed;
}

.connection-defaults th,
.connection-defaults td {
  text-align: left;
  white-space: normal;
  overflow-wrap: anywhere;
}

.connection-defaults thead th:first-child {
  width: 47%;
}

.connection-defaults tbody th {
  font-weight: 500;
}

@media (max-width: 1023px) {
  .connection-defaults th,
  .connection-defaults td {
    padding-inline: 8px;
  }

  .connection-defaults thead th:first-child {
    width: 39%;
  }
}
</style>
