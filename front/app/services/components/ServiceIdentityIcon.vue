<template>
  <ServiceIcon :icon="service?.icon" :fallback="fallback" :size="size" :label="label" />
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { navigationIcon } from '@/core/navigation'
import { internalServiceIcon } from '../presentation'
import type { Service } from '../services/serviceApi'
import ServiceIcon from './ServiceIcon.vue'

const { service, size = 24, label = '' } = defineProps<{
  service?: Pick<Service, 'code' | 'can_edit' | 'icon'> | null
  size?: number
  label?: string
}>()
const fallback = computed(() => navigationIcon(service ? internalServiceIcon(service) : 'hub'))
</script>
