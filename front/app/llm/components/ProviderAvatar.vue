<template>
  <q-avatar
    :size="size"
    :color="showLogo ? 'white' : item.color"
    text-color="white"
    class="provider-avatar"
    :class="{ 'provider-avatar--logo': showLogo }"
    aria-hidden="true"
  >
    <img v-if="showLogo" :src="logo!" alt="" class="provider-logo" @error="failedLogo = logo" />
    <q-icon v-else :name="item.icon" size="0.6em" />
  </q-avatar>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ProviderCatalogItem } from '../services/llmProviderService'
import { providerLogo } from '../providerUi'

const { item, size = '34px' } = defineProps<{
  item: Pick<ProviderCatalogItem, 'code' | 'icon' | 'color'>
  size?: string
}>()

const logo = computed(() => providerLogo(item.code))
const failedLogo = ref<string | null>(null)
const showLogo = computed(() => Boolean(logo.value && failedLogo.value !== logo.value))
</script>

<style scoped>
.provider-avatar--logo {
  border: 1px solid rgba(0, 0, 0, 0.1);
}

.provider-avatar .provider-logo {
  width: 72%;
  height: 72%;
  object-fit: contain;
  border-radius: 0;
}
</style>
