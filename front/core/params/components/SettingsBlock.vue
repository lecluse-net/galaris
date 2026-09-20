<template>
    <section class="settings-block" :aria-label="title">
        <q-expansion-item v-if="advanced" :label="title" :caption="description" :icon="icon"
            header-class="settings-block__header" expand-icon="expand_more">
            <div class="settings-block__body"><slot /></div>
        </q-expansion-item>
        <template v-else>
            <div class="settings-block__header row items-start no-wrap q-gutter-sm">
                <q-icon v-if="icon" :name="icon" color="primary" size="22px" class="q-mt-xs" />
                <div>
                    <h2 class="text-subtitle1 text-weight-medium q-ma-none">{{ title }}</h2>
                    <p v-if="description" class="text-body2 text-grey-7 q-mt-xs q-mb-none">{{ description }}</p>
                </div>
            </div>
            <div class="settings-block__body"><slot /></div>
        </template>
    </section>
</template>

<script setup lang="ts">
defineProps<{ title: string; description?: string; icon?: string; advanced?: boolean }>()
</script>

<style scoped>
.settings-block {
    min-width: 0;
    border: 1px solid color-mix(in srgb, currentColor 16%, transparent);
    border-radius: 12px;
    margin-bottom: 20px;
    overflow: hidden;
}
.settings-block :deep(.settings-block__header) {
    padding: 16px 20px;
    background: var(--solaire-gray-light);
}
.settings-block__body { padding: 8px 20px 20px; }
body.body--dark .settings-block :deep(.settings-block__header) { background: var(--solaire-gray-dark); }
@media (max-width: 1023px) {
    .settings-block :deep(.settings-block__header) { padding: 14px; }
    .settings-block__body { padding: 8px 14px 14px; }
}
</style>
