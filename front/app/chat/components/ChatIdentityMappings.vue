<template>
  <section class="relative-position" :aria-label="t('chat.identity.title')">
    <q-separator />
    <q-card-section>
      <div class="row items-center q-gutter-sm">
        <q-icon name="link" color="primary" size="sm" />
        <div class="text-subtitle2">{{ t('chat.identity.title') }}</div>
      </div>
      <div class="text-caption text-grey-7 q-mt-xs">{{ t('chat.identity.hint') }}</div>
    </q-card-section>
    <q-separator />
    <q-list v-if="mappings.length" separator>
      <q-item v-for="mapping in mappings" :key="mapping.tool_id" class="identity-row">
        <q-item-section>
          <q-item-label class="row items-center q-gutter-xs">
            <span>{{ mapping.tool_label }}</span>
            <q-badge outline color="grey-7" :label="t(sourceTranslationKey(mapping.source))" />
          </q-item-label>
          <q-input
            v-model.trim="externalIds[mapping.tool_id]"
            dense
            outlined
            class="q-mt-sm"
            :label="t('chat.identity.externalId')"
            :hint="mapping.display_name && mapping.display_name !== mapping.external_id ? mapping.display_name : undefined"
            @keyup.enter="save(mapping.tool_id)"
          />
        </q-item-section>
        <q-item-section side top class="identity-actions">
          <q-btn flat round dense color="primary" icon="save" :loading="savingToolId === mapping.tool_id" :aria-label="t('common.save')" @click="save(mapping.tool_id)" />
          <q-btn v-if="mapping.external_id" flat round dense color="negative" icon="link_off" :disable="savingToolId !== null" :aria-label="t('chat.identity.unlink')" @click="clear(mapping.tool_id)" />
        </q-item-section>
      </q-item>
    </q-list>
    <q-card-section v-else-if="!loading" class="text-caption text-grey-7">{{ t('chat.identity.noTools') }}</q-card-section>
    <q-inner-loading :showing="loading" />
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { chatService } from '../services/chatService'
import { sourceTranslationKey } from '../sourcePresentation'
import type { ChatIdentityMapping } from '../types'

const { t } = useI18n()
const $q = useQuasar()
const mappings = ref<ChatIdentityMapping[]>([])
const externalIds = reactive<Record<number, string>>({})
const loading = ref(false)
const savingToolId = ref<number | null>(null)

async function load(): Promise<void> {
  loading.value = true
  try {
    mappings.value = await chatService.identityMappings()
    for (const mapping of mappings.value) externalIds[mapping.tool_id] = mapping.external_id ?? ''
  } catch (error) {
    $q.notify({ type: 'negative', message: apiErrorDetail(error) ?? t('chat.identity.loadError') })
  } finally {
    loading.value = false
  }
}

async function save(toolId: number): Promise<void> {
  const externalId = externalIds[toolId]?.trim()
  if (!externalId || savingToolId.value !== null) return
  savingToolId.value = toolId
  try {
    await chatService.setIdentityMapping(toolId, externalId)
    await load()
    $q.notify({ type: 'positive', message: t('chat.identity.saved') })
  } catch (error) {
    $q.notify({ type: 'negative', message: apiErrorDetail(error) ?? t('chat.identity.saveError') })
  } finally {
    savingToolId.value = null
  }
}

async function clear(toolId: number): Promise<void> {
  if (savingToolId.value !== null) return
  savingToolId.value = toolId
  try {
    await chatService.clearIdentityMapping(toolId)
    await load()
    $q.notify({ type: 'positive', message: t('chat.identity.cleared') })
  } catch (error) {
    $q.notify({ type: 'negative', message: apiErrorDetail(error) ?? t('chat.identity.saveError') })
  } finally {
    savingToolId.value = null
  }
}

onMounted(() => void load())
</script>

<style scoped>
.identity-row { align-items: flex-start; padding-block: 14px; }
.identity-actions { display: flex; flex-direction: row; gap: 2px; }
</style>
