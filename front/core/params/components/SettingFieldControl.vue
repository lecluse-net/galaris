<template>
    <div class="setting-field q-py-sm">
        <PromptSettingEditor v-if="field.input === 'prompt'" :field="field" />

        <div v-else-if="field.input === 'checkbox'" class="row items-start no-wrap">
            <q-checkbox
                :model-value="localValue === 'true'"
                color="primary"
                :label="t(field.labelKey)"
                :disable="saving || !canEdit"
                @update:model-value="saveBoolean"
            />
            <q-spinner v-if="saving" size="sm" color="primary" class="q-ml-sm q-mt-sm" />
        </div>

        <div v-else-if="field.input === 'boolean'" class="row items-start no-wrap">
            <q-toggle
                :model-value="localValue === 'true'"
                color="primary"
                :label="t(field.labelKey)"
                :disable="saving || !canEdit"
                @update:model-value="saveBoolean"
            />
            <q-spinner v-if="saving" size="sm" color="primary" class="q-ml-sm q-mt-sm" />
        </div>

        <q-select
            v-else-if="field.input === 'select'"
            v-model="localValue"
            :options="selectOptions"
            emit-value
            map-options
            outlined
            dense
            :label="t(field.labelKey)"
            :loading="saving"
            :disable="!canEdit"
            @update:model-value="saveValue"
        />

        <CodeEditor
            v-else-if="field.input === 'code'"
            :model-value="localValue ?? ''"
            :language="field.codeLanguage ?? 'text'"
            :label="t(field.labelKey)"
            :visible-lines="field.visibleLines ?? 12"
            :readonly="!canEdit"
            @update:model-value="value => localValue = value"
            @focusout="saveValue"
        />

        <div v-else-if="field.input === 'percentage-slider'" class="percentage-slider q-px-sm">
            <div class="row items-center justify-between q-mb-sm">
                <div :id="`${field.name}-label`" class="text-body2 text-weight-medium">
                    {{ t(field.labelKey) }}
                </div>
                <q-badge color="primary" rounded class="percentage-slider__value">
                    {{ percentageValue }} %
                </q-badge>
            </div>
            <q-slider
                :model-value="percentageValue"
                :min="field.min ?? 0"
                :max="field.max ?? 100"
                :step="field.step ?? 1"
                color="primary"
                label
                label-always
                :label-value="`${percentageValue} %`"
                :disable="saving || !canEdit"
                :aria-labelledby="`${field.name}-label`"
                @update:model-value="updatePercentage"
                @change="savePercentage"
            />
            <div class="row justify-between text-caption text-grey-6 percentage-slider__bounds">
                <span>{{ field.min ?? 0 }} %</span>
                <span>{{ field.max ?? 100 }} %</span>
            </div>
        </div>

        <q-input
            v-else
            v-model="localValue"
            :type="inputType"
            :min="displayBound(field.min)"
            :max="displayBound(field.max)"
            :step="field.sizeUnit ? displayBound(field.step ?? 1) : field.step"
            :rules="field.sizeUnit ? [validSize] : undefined"
            lazy-rules
            outlined
            dense
            :autogrow="field.input === 'textarea'"
            :label="t(field.labelKey)"
            :loading="saving"
            :readonly="!canEdit"
            :placeholder="param?.secret && param.configured ? t('configuration.secretUnchanged') : undefined"
            @blur="saveValue"
            @keyup.enter="field.input !== 'textarea' && saveValue()"
        >
            <template v-if="param?.secret" #append>
                <q-icon v-if="param.configured" name="verified_user" color="positive">
                    <q-tooltip>{{ t('configuration.secretConfigured') }}</q-tooltip>
                </q-icon>
                <q-btn
                    v-if="canEdit && param.configured"
                    flat
                    round
                    dense
                    icon="delete_outline"
                    color="negative"
                    :aria-label="t('configuration.clearSecret')"
                    @click.stop="confirmClearSecret"
                />
            </template>
        </q-input>

        <div v-if="field.descriptionKey && field.input !== 'prompt'" class="text-caption text-grey-7 q-mt-xs">
            {{ t(field.descriptionKey) }}
        </div>
    </div>
</template>

<script setup lang="ts">
import { showConfirmationDialog, sizeInMegabytes, sizeFromMegabytes } from '@/core/util'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import type { QInputProps } from 'quasar'
import { CodeEditor } from '@/core/util'
import type { SettingField } from '../settingsTypes'
import { useParamsStore } from '../stores/paramsStore'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import PromptSettingEditor from './PromptSettingEditor.vue'

const props = defineProps<{ field: SettingField }>()
const { t } = useI18n()
const $q = useQuasar()
const paramsStore = useParamsStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))
const localValue = ref<string | null>('')
const saving = ref(false)

const param = computed(() => paramsStore.getParamByName(props.field.name))
const inputType = computed<QInputProps['type']>(() => {
    if (props.field.input === 'secret') return 'password'
    if (props.field.input === 'integer' || props.field.input === 'number') return 'number'
    if (props.field.input === 'textarea') return 'textarea'
    return 'text'
})
const selectOptions = computed(() => (props.field.options ?? []).map(option => ({
    value: option.value,
    label: t(option.labelKey),
})))
const percentageValue = computed(() => {
    const fallback = props.field.min ?? 0
    const value = Number(localValue.value)
    if (!Number.isFinite(value)) return fallback
    return Math.max(fallback, Math.min(props.field.max ?? 100, Math.round(value * 100)))
})

watch(param, current => {
    localValue.value = displayValue(current?.secret ? '' : (current?.value ?? ''))
}, { immediate: true, deep: true })

function displayBound(value: number | undefined): number | undefined {
    return value === undefined || !props.field.sizeUnit ? value : sizeInMegabytes(value, props.field.sizeUnit)
}

function displayValue(value: string): string {
    return !props.field.sizeUnit || value === '' ? value : String(sizeInMegabytes(Number(value), props.field.sizeUnit))
}

function validSize(value: string | number | null): true | string {
    const stored = sizeFromMegabytes(Number(value), props.field.sizeUnit)
    return (value !== null && value !== '' && Number.isFinite(stored)
        && (props.field.input !== 'integer' || Number.isInteger(stored))
        && stored >= (props.field.min ?? 0) && (props.field.max === undefined || stored <= props.field.max))
        || t('configuration.invalidFileSize', { step: displayBound(props.field.step ?? 1) })
}

function notify(ok: boolean): void {
    $q.notify({
        type: ok ? 'positive' : 'negative',
        message: t(ok ? 'configuration.saved' : 'configuration.saveError'),
        timeout: ok ? 1400 : 3000,
    })
}

async function persist(value: string | null, clearSecret = false): Promise<void> {
    if (!canEdit.value || saving.value) return
    if (param.value?.secret && !clearSecret && !value) return
    if (!param.value?.secret && value === (param.value?.value ?? '')) return
    saving.value = true
    try {
        await paramsStore.updateParam(props.field.name, value, clearSecret)
        if (param.value?.secret) localValue.value = ''
        notify(true)
    } catch {
        localValue.value = displayValue(param.value?.secret ? '' : (param.value?.value ?? ''))
        notify(false)
    } finally {
        saving.value = false
    }
}

function saveBoolean(value: boolean): void {
    localValue.value = value ? 'true' : 'false'
    void persist(localValue.value)
}

function saveValue(): void {
    if (props.field.sizeUnit) {
        if (validSize(localValue.value) !== true) return
        void persist(String(sizeFromMegabytes(Number(localValue.value), props.field.sizeUnit)))
        return
    }
    void persist(localValue.value === null ? null : String(localValue.value))
}

function updatePercentage(value: number | null): void {
    if (value === null) return
    localValue.value = (value / 100).toFixed(2)
}

function savePercentage(value: number | null): void {
    updatePercentage(value)
    void persist(localValue.value)
}

function confirmClearSecret(): void {
    showConfirmationDialog({
        title: t('configuration.clearSecretTitle'),
        message: t('configuration.clearSecretMessage'),
        cancel: true,
    }).onOk(() => void persist(null, true))
}
</script>

<style scoped>
.setting-field + .setting-field {
    border-top: 1px solid rgba(0, 0, 0, 0.08);
}

body.body--dark .setting-field + .setting-field {
    border-top-color: rgba(255, 255, 255, 0.12);
}

.percentage-slider {
    padding-top: 6px;
}

.percentage-slider__value {
    min-width: 52px;
    justify-content: center;
    font-variant-numeric: tabular-nums;
}

.percentage-slider__bounds {
    margin-top: -8px;
}
</style>
