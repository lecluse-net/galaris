<template>
    <div>
        <div class="settings-fields" :class="{ 'settings-fields--columns': columns === 2 }">
            <SettingFieldControl
                v-for="field in basicFields"
                :key="field.name"
                :field="field"
                :class="{ 'settings-fields__wide': isWide(field) }"
            />
        </div>

        <q-expansion-item
            v-if="advancedFields.length"
            icon="tune"
            :label="advancedLabel || t('configuration.advanced')"
            header-class="text-primary"
            class="q-mt-md settings-advanced"
        >
            <div class="settings-fields q-px-md q-pb-md" :class="{ 'settings-fields--columns': columns === 2 }">
                <SettingFieldControl
                    v-for="field in advancedFields"
                    :key="field.name"
                    :field="field"
                    :class="{ 'settings-fields__wide': isWide(field) }"
                />
            </div>
        </q-expansion-item>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SettingField } from '../settingsTypes'
import SettingFieldControl from './SettingFieldControl.vue'

const props = withDefaults(defineProps<{
    fields: SettingField[]
    columns?: 1 | 2
    expandAdvanced?: boolean
    advancedLabel?: string
}>(), { columns: 1, expandAdvanced: true })
const { t } = useI18n()
const basicFields = computed(() => props.fields.filter(field => !props.expandAdvanced || !field.advanced))
const advancedFields = computed(() => props.expandAdvanced ? props.fields.filter(field => field.advanced) : [])
function isWide(field: SettingField): boolean {
    return ['prompt', 'code', 'textarea', 'boolean', 'checkbox'].includes(field.input ?? '')
}
</script>

<style scoped>
.settings-fields { min-width: 0; }
.settings-fields > :deep(*) { min-width: 0; }
.settings-fields--columns > :deep(.setting-field) { border-top: 0; }
.settings-fields--columns :deep(.percentage-slider .q-slider) { margin-top: 20px; }
@media (min-width: 1024px) {
    .settings-fields--columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; }
    .settings-fields__wide { grid-column: 1 / -1; }
}
.settings-advanced {
    border: 1px solid rgba(0, 0, 0, 0.1);
    border-radius: 8px;
}

body.body--dark .settings-advanced {
    border-color: rgba(255, 255, 255, 0.16);
}
</style>
