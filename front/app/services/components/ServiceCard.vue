<template>
  <q-card tag="article" flat bordered class="service-card" :aria-label="label">
    <div class="service-card-content" :class="{ 'cursor-pointer': description }" @click="description && emit('describe')">
      <div class="service-card-icon bg-grey-2"><ServiceIdentityIcon :service="service" :size="$q.screen.lt.sm ? 64 : 80" /></div>
      <q-card-section class="service-card-details q-pa-md">
        <div class="row items-start no-wrap q-gutter-xs">
          <!-- eslint-disable-next-line galaris/ui-conventions -- Keep the service name styled as a heading. -->
          <q-btn v-if="description" flat dense no-caps align="left" class="service-card-title text-h6 text-weight-bold"
            :label="label" @click.stop="emit('describe')" />
          <h2 v-else class="service-card-title text-h6 text-weight-bold q-ma-none">{{ label }}</h2>
          <SystemServiceIcon v-if="service.can_disable === false" class="q-mt-sm" />
        </div>
        <div class="text-caption service-card-code">{{ service.code }}</div>
        <p class="service-card-description text-body2 q-mt-sm q-mb-md">{{ excerpt || t('services.noDescription') }}</p>
        <ServiceCapabilities :tool="service" :definitions="definitions" />
      </q-card-section>
    </div>
    <q-separator />
    <div class="row items-center justify-between q-px-md q-py-xs service-card-status">
      <span class="row items-center no-wrap q-gutter-xs text-caption">
        <q-icon name="link" color="primary" size="18px" />
        <span>{{ t('services.connectionCount', service.connection_count ?? 0) }}</span>
      </span>
      <q-toggle :model-value="service.conversation_enabled" size="sm" color="primary"
        :label="t('services.conversationAccess')"
        :aria-label="t('services.conversationAccessFor', { name: label })"
        :disable="!canEdit || service.can_disable === false || busy"
        @update:model-value="value => emit('conversation', value)">
        <q-tooltip>{{ t('services.conversationAccessHint') }}</q-tooltip>
      </q-toggle>
      <q-spinner v-if="busy" size="18px" color="primary" />
    </div>
    <q-card-actions align="right" class="q-pa-sm service-card-actions">
      <!-- eslint-disable-next-line galaris/ui-conventions -- Restore the borderless service card action. -->
      <q-btn v-if="service.can_edit" flat color="secondary" icon="download" size="sm" :label="t('services.exportYaml')"
        :aria-label="t('services.exportYaml')" @click="emit('export')"><q-tooltip>{{ t('services.exportYaml') }}</q-tooltip></q-btn>
      <!-- eslint-disable-next-line galaris/ui-conventions -- Restore the borderless service card action. -->
      <q-btn flat v-if="canEdit && service.can_disable !== false && Object.keys(service.connection_schema?.params ?? {}).length"
        color="solaire-iris" icon="tune" size="sm" :label="t('services.globalParams')"
        :aria-label="t('services.globalParams')" @click="emit('parameters')"><q-tooltip>{{ t('services.globalParams') }}</q-tooltip></q-btn>
      <!-- eslint-disable-next-line galaris/ui-conventions -- Restore the borderless service card action. -->
      <q-btn v-if="canEdit && service.can_edit && service.can_disable !== false" flat style="color: #D1B306" icon="edit" size="sm"
        :label="t('common.edit')" :aria-label="t('services.editService')" @click="emit('edit')"><q-tooltip>{{ t('services.editService') }}</q-tooltip></q-btn>
      <!-- eslint-disable-next-line galaris/ui-conventions -- Restore the borderless service card action. -->
      <q-btn v-if="canEdit && service.can_edit && service.can_disable !== false" flat color="negative" icon="delete" size="sm"
        :label="t('common.delete')" :aria-label="t('common.delete')" @click="emit('delete')"><q-tooltip>{{ t('common.delete') }}</q-tooltip></q-btn>
    </q-card-actions>
  </q-card>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { marked } from 'marked'
import { richTextExcerpt } from '@/core/util'
import type { CapabilityDefinition, Service } from '../services/serviceApi'
import ServiceIdentityIcon from './ServiceIdentityIcon.vue'
import ServiceCapabilities from './ServiceCapabilities.vue'
import SystemServiceIcon from './SystemServiceIcon.vue'

const { service, label, description, definitions, canEdit, busy } = defineProps<{
  service: Service; label: string; description: string; definitions: CapabilityDefinition[]; canEdit: boolean; busy: boolean
}>()
const emit = defineEmits<{
  describe: []; export: []; parameters: []; edit: []; delete: []; conversation: [enabled: boolean]
}>()
const { t } = useI18n()
const excerpt = computed(() => richTextExcerpt(marked.parse(description.replace(/^#{1,6}\s+.*$/gm, ''), { async: false })))
</script>
<style scoped>
.service-card { display: flex; flex-direction: column; min-width: 0; height: 100%; }
.service-card-content { display: grid; grid-template-columns: 120px minmax(0, 1fr); flex: 1; }
.service-card-icon { display: flex; align-items: center; justify-content: center; padding: 16px; }
.service-card-details, .service-card-title { min-width: 0; }
.service-card-title { flex: 1; line-height: 1.35; overflow-wrap: anywhere; }
.service-card-title :deep(.q-btn__content) { justify-content: flex-start; text-align: left; white-space: normal; }
.service-card-code { color: var(--solaire-gray-accent); overflow-wrap: anywhere; }
.service-card-description { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; min-height: 4.5em; overflow-wrap: anywhere; }
.service-card-status { gap: 4px 12px; }
.service-card-actions { gap: 4px; }
@media (max-width: 599px) {
  .service-card-content { grid-template-columns: 84px minmax(0, 1fr); }
  .service-card-icon { padding: 8px; }
}
</style>
