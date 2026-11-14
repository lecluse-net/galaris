<template>
  <div class="row items-center q-gutter-sm">
    <ServiceIcon :icon="model" :label="t('services.icon')" :size="40" />
    <q-file outlined dense :model-value="file" :label="t('services.chooseIcon')"
      accept="image/svg+xml,image/png,image/gif" :max-file-size="131072" class="col"
      @update:model-value="read" @rejected="error = t('services.iconError')" />
    <q-btn v-if="model" flat round color="negative" icon="delete" :aria-label="t('services.removeIcon')" @click="clear" />
    <div v-if="error" role="alert" class="col-12 text-negative">{{ error }}</div>
  </div>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ServiceIcon from './ServiceIcon.vue'
import type { ServiceIcon as Icon } from '../services/serviceApi'
const model = defineModel<Icon | null>({ required: true })
const { t } = useI18n()
const file = ref<File | null>(null), error = ref('')
let generation = 0
onBeforeUnmount(() => generation++)
function clear() { generation++; model.value = null; file.value = null; error.value = '' }
async function read(value: File | null) {
  const current = ++generation
  file.value = value; error.value = ''
  if (!value) return
  const types = ['image/svg+xml', 'image/png', 'image/gif'] as const
  const mediaType = types.find(type => type === value.type)
  if (!mediaType || value.size > 131072) { error.value = t('services.iconError'); return }
  try {
    const bytes = new Uint8Array(await value.arrayBuffer())
    const data = mediaType === 'image/svg+xml' ? new TextDecoder().decode(bytes)
      : btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join(''))
    if (current === generation) model.value = { media_type: mediaType,
      encoding: mediaType === 'image/svg+xml' ? 'text' : 'base64', data }
  } catch { if (current === generation) error.value = t('services.iconError') }
}
</script>
