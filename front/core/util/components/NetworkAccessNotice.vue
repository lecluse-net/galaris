<template>
    <q-banner v-if="network" rounded :class="['network-notice', { 'network-notice--warning': warning }]" :role="warning ? 'alert' : 'note'" :aria-label="bridge?.label">
        <template #avatar>
            <q-icon :name="warning ? 'warning' : 'info_outline'" class="network-notice__icon" />
        </template>
        <div>{{ t(network.hintKey) }}</div>
        <div v-if="warning && network.warningKey" class="q-mt-sm">
            {{ t(network.warningKey, { origin: address?.origin ?? origin }) }}
        </div>
    </q-banner>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { isPrivateHostname, type NetworkAccessRequirement } from '../networkAddress'

const modules = import.meta.glob<{ default: NetworkAccessRequirement }>(
    '../../../bridge/*/network.ts', { eager: true },
)
const requirements = Object.values(modules).map(module => module.default)

const props = withDefaults(defineProps<{ kind: string; origin?: string }>(), {
    origin: () => window.location.origin,
})
const { t } = useI18n()
const bridge = computed(() => requirements.find(item => item.kind === props.kind))
const network = bridge
const address = computed(() => {
    try { return new URL(props.origin) } catch { return null }
})
const warning = computed(() => {
    if (!network.value || network.value.mode === 'outbound') return false
    return !address.value || isPrivateHostname(address.value.hostname)
        || network.value.mode === 'public-https' && address.value.protocol !== 'https:'
})
</script>

<style scoped>
.network-notice {
    background: var(--solaire-blue-light);
    overflow-wrap: anywhere;
}
.network-notice__icon { color: var(--solaire-blue-accent); }
.network-notice--warning { background: var(--solaire-orange-light); }
.network-notice--warning .network-notice__icon { color: var(--solaire-orange-accent); }
.body--dark .network-notice { background: var(--solaire-blue-dark); }
.body--dark .network-notice--warning { background: var(--solaire-orange-dark); }
</style>
