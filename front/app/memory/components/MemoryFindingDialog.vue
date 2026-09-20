<template>
  <q-dialog :model-value="true" :maximized="$q.screen.lt.md" @hide="emit('close')">
    <q-card class="finding-dialog column no-wrap">
      <q-toolbar class="galaris-dialog-title">
        <q-icon :name="kindIcon" size="sm" class="q-mr-sm" />
        <q-toolbar-title>{{ t(`memory.findings.kinds.${finding.kind}`) }}</q-toolbar-title>
        <q-btn flat round dense icon="close" :aria-label="$t('common.close')" v-close-popup />
      </q-toolbar>

      <q-inner-loading :showing="loading" />
      <q-scroll-area class="col">
        <q-card-section>
          <q-banner rounded class="bg-blue-1 text-primary q-mb-md">
            {{ explanation }}
            <div v-if="finding.score !== null" class="text-caption q-mt-xs">
              {{ t('memory.findings.score', {
                score: formatPercentage(finding.score),
                threshold: formatPercentage(finding.threshold),
              }) }}
            </div>
          </q-banner>

          <div class="row q-col-gutter-md">
            <div
              v-for="item in comparedItems"
              :key="item.id"
              class="col-12"
              :class="related ? 'col-md-6' : ''"
            >
              <q-card flat bordered class="full-height">
                <q-card-section>
                  <div class="row items-center no-wrap q-gutter-sm">
                    <q-radio
                      v-if="related"
                      v-model="canonicalItemId"
                      :val="item.id"
                      :aria-label="t('memory.findings.keepThis')"
                    />
                    <div>
                      <div class="text-subtitle1 text-weight-medium">{{ item.title }}</div>
                      <div class="text-caption text-grey-7">
                        {{ t('memory.findings.revisionDate', { revision: item.revision, date: formatDate(item.updated_at || item.created_at) }) }}
                      </div>
                    </div>
                  </div>
                  <q-chip v-if="related && canonicalItemId === item.id" dense color="primary" text-color="white" icon="check">
                    {{ t('memory.findings.kept') }}
                  </q-chip>
                  <pre v-if="item.payload.text != null" class="finding-content">{{ item.payload.text }}</pre>
                  <q-banner v-else rounded class="bg-grey-2">{{ t('memory.binaryContent') }}</q-banner>
                </q-card-section>
              </q-card>
            </div>
          </div>
        </q-card-section>
      </q-scroll-area>

      <q-separator />
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn
          flat
          color="grey-8"
          icon="visibility_off"
          :label="t('memory.findings.dismiss')"
          :loading="saving"
          @click="resolve('dismiss')"
        />
        <q-btn
          color="primary"
          :icon="finding.kind === 'aging' ? 'history' : 'merge_type'"
          :label="finding.kind === 'aging' ? t('memory.findings.markOld') : t('memory.findings.merge')"
          :disable="related !== null && canonicalItemId === null"
          :loading="saving"
          @click="resolve('apply')"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { memoryService } from '../services/memoryService'
import type { MemoryFinding, MemoryItemDetail } from '../types'

const props = defineProps<{ finding: MemoryFinding, agentId: number, saving: boolean }>()
const emit = defineEmits<{
  close: []
  resolved: [action: 'apply' | 'dismiss', canonicalItemId?: string]
}>()
const { t, locale } = useI18n()
const $q = useQuasar()
const primary = ref<MemoryItemDetail | null>(null)
const related = ref<MemoryItemDetail | null>(null)
const loading = ref(true)
const proposedCanonicalId = typeof props.finding.details.proposed_canonical_item_id === 'string'
  ? props.finding.details.proposed_canonical_item_id
  : props.finding.primary_item_id
const canonicalItemId = ref<string | null>(
  props.finding.related_item_id === null ? null : proposedCanonicalId,
)
const comparedItems = computed(() => [primary.value, related.value].filter(
  (item): item is MemoryItemDetail => item !== null,
))
const kindIcon = computed(() => ({
  duplicate: 'content_copy', contradiction: 'compare_arrows', aging: 'history',
})[props.finding.kind])
const explanation = computed(() => t(`memory.findings.explanations.${props.finding.kind}`))

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function formatPercentage(value: number): string {
  return new Intl.NumberFormat(locale.value, {
    style: 'percent',
    maximumFractionDigits: 1,
  }).format(value)
}

function resolve(action: 'apply' | 'dismiss'): void {
  emit('resolved', action, canonicalItemId.value ?? undefined)
}

onMounted(async () => {
  try {
    const [first, second] = await Promise.all([
      memoryService.getItem(props.finding.primary_item_id, props.agentId),
      props.finding.related_item_id
        ? memoryService.getItem(props.finding.related_item_id, props.agentId)
        : Promise.resolve(null),
    ])
    primary.value = first
    related.value = second
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.finding-dialog {
  width: min(1100px, 96vw);
  height: min(760px, 92vh);
}

.finding-content {
  margin: 0;
  max-height: 420px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
}
</style>
