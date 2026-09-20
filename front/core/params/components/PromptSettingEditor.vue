<template>
    <q-card flat bordered class="prompt-editor">
        <q-card-section class="q-pb-sm">
            <div class="row items-start justify-between q-col-gutter-sm">
                <div class="col">
                    <div class="text-subtitle2">{{ t(field.labelKey) }}</div>
                    <div v-if="field.descriptionKey" class="text-caption text-grey-7 q-mt-xs">
                        {{ t(field.descriptionKey) }}
                    </div>
                </div>
                <q-chip
                    dense
                    :color="status.color"
                    :text-color="status.textColor"
                    :icon="status.icon"
                >
                    {{ status.label }}
                </q-chip>
            </div>
        </q-card-section>

        <q-banner
            v-if="metadata?.default_changed"
            rounded
            class="prompt-editor__conflict bg-orange-1 text-orange-10 q-mx-md q-mb-md"
        >
            <template #avatar><q-icon name="difference" color="warning" /></template>
            <div class="text-subtitle2">{{ t('promptEditor.defaultChangedTitle') }}</div>
            <div class="text-body2">{{ t('promptEditor.defaultChangedMessage') }}</div>
            <template #action>
                <q-btn
                    flat
                    no-caps
                    color="orange-10"
                    :label="t('promptEditor.keepCustom')"
                    :loading="savingAction === 'keep_custom'"
                    :disable="!canEdit || saving"
                    @click="keepCustom"
                />
                <q-btn
                    unelevated
                    no-caps
                    color="primary"
                    :label="t('promptEditor.useNewDefault')"
                    :disable="!canEdit || saving"
                    @click="openUseDefaultDialog"
                />
            </template>
        </q-banner>

        <q-card-section class="q-pt-none">
            <CodeEditor
                v-model="draft"
                language="markdown"
                :label="t('promptEditor.content')"
                :visible-lines="field.visibleLines ?? 18"
                :readonly="!canEdit || saving"
                :show-error="false"
            />

            <div class="row items-center q-gutter-sm q-mt-md">
                <q-btn
                    color="primary"
                    icon="save"
                    no-caps
                    :label="t('promptEditor.save')"
                    :loading="savingAction === 'save'"
                    :disable="!canEdit || saving || !dirty"
                    @click="save"
                />
                <q-btn
                    outline
                    color="primary"
                    icon="restore"
                    no-caps
                    :label="t('promptEditor.restoreDefault')"
                    :disable="!canEdit || saving || !metadata?.customized"
                    @click="openUseDefaultDialog"
                />
                <q-btn
                    flat
                    color="primary"
                    :icon="showDiff ? 'visibility_off' : 'difference'"
                    no-caps
                    :label="t(showDiff ? 'promptEditor.hideDiff' : 'promptEditor.showDiff')"
                    @click="showDiff = !showDiff"
                />
            </div>

            <q-slide-transition>
                <div v-if="showDiff" class="prompt-editor__diff q-mt-md">
                    <div class="row items-center q-gutter-md text-caption q-mb-sm">
                        <span><q-icon name="remove" color="negative" /> {{ t('promptEditor.defaultVersion') }}</span>
                        <span><q-icon name="add" color="positive" /> {{ t('promptEditor.editedVersion') }}</span>
                    </div>
                    <pre class="prompt-editor__diff-lines"><span
                        v-for="(line, index) in diffLines"
                        :key="`${index}-${line.kind}`"
                        :class="`prompt-editor__diff-line prompt-editor__diff-line--${line.kind}`"
                    ><span class="prompt-editor__diff-marker">{{ diffMarker(line.kind) }}</span>{{ line.text || ' ' }}</span></pre>
                </div>
            </q-slide-transition>
        </q-card-section>
    </q-card>

    <q-dialog v-model="useDefaultDialog">
        <q-card class="prompt-editor__dialog">
            <q-card-section class="galaris-dialog-title row items-center">
                <div class="text-h6">{{ t('promptEditor.restoreTitle') }}</div>
                <q-space />
                <q-btn
                    v-close-popup
                    flat
                    round
                    dense
                    icon="close"
                    :aria-label="t('common.close')"
                />
            </q-card-section>
            <q-card-section>{{ t('promptEditor.restoreMessage') }}</q-card-section>
            <q-separator />
            <q-card-actions class="galaris-dialog-actions" align="right">
                <q-btn v-close-popup flat no-caps :label="t('common.cancel')" />
                <q-btn
                    unelevated
                    no-caps
                    color="primary"
                    :label="t('promptEditor.useDefault')"
                    :loading="savingAction === 'use_default'"
                    @click="useDefault"
                />
            </q-card-actions>
        </q-card>
    </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { CodeEditor } from '@/core/util'
import type { PromptAction } from '../services/paramsService'
import type { SettingField } from '../settingsTypes'
import { useParamsStore } from '../stores/paramsStore'

type DiffKind = 'same' | 'added' | 'removed'
interface DiffLine { kind: DiffKind; text: string }
type PersistAction = 'save' | PromptAction
type SavingAction = PersistAction | null

const { field } = defineProps<{ field: SettingField }>()
const { t } = useI18n()
const $q = useQuasar()
const paramsStore = useParamsStore()
const privilegeStore = usePrivilegeStore()
const draft = ref('')
const showDiff = ref(false)
const useDefaultDialog = ref(false)
const savingAction = ref<SavingAction>(null)

const param = computed(() => paramsStore.getParamByName(field.name))
const metadata = computed(() => param.value?.prompt ?? null)
const currentValue = computed(() => param.value?.value ?? metadata.value?.default_value ?? '')
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))
const saving = computed(() => savingAction.value !== null)
const dirty = computed(() => draft.value !== currentValue.value)
const status = computed(() => {
    if (metadata.value?.default_changed) {
        return { color: 'warning', textColor: 'dark', icon: 'upgrade', label: t('promptEditor.statusUpdate') }
    }
    if (metadata.value?.customized) {
        return { color: 'secondary', textColor: 'white', icon: 'edit', label: t('promptEditor.statusCustom') }
    }
    return { color: 'positive', textColor: 'white', icon: 'sync', label: t('promptEditor.statusDefault') }
})
const diffLines = computed(() => buildLineDiff(metadata.value?.default_value ?? '', draft.value))

watch(currentValue, value => {
    draft.value = value
}, { immediate: true })

function buildLineDiff(defaultValue: string, editedValue: string): DiffLine[] {
    const before = defaultValue.split('\n')
    const after = editedValue.split('\n')
    const lengths = Array.from({ length: before.length + 1 }, () =>
        Array<number>(after.length + 1).fill(0))
    for (let left = before.length - 1; left >= 0; left -= 1) {
        for (let right = after.length - 1; right >= 0; right -= 1) {
            lengths[left][right] = before[left] === after[right]
                ? lengths[left + 1][right + 1] + 1
                : Math.max(lengths[left + 1][right], lengths[left][right + 1])
        }
    }
    const result: DiffLine[] = []
    let left = 0
    let right = 0
    while (left < before.length && right < after.length) {
        if (before[left] === after[right]) {
            result.push({ kind: 'same', text: before[left] })
            left += 1
            right += 1
        } else if (lengths[left + 1][right] >= lengths[left][right + 1]) {
            result.push({ kind: 'removed', text: before[left] })
            left += 1
        } else {
            result.push({ kind: 'added', text: after[right] })
            right += 1
        }
    }
    while (left < before.length) result.push({ kind: 'removed', text: before[left++] })
    while (right < after.length) result.push({ kind: 'added', text: after[right++] })
    return result
}

function diffMarker(kind: DiffKind): string {
    if (kind === 'added') return '+ '
    if (kind === 'removed') return '- '
    return '  '
}

function notify(ok: boolean): void {
    $q.notify({
        type: ok ? 'positive' : 'negative',
        message: t(ok ? 'configuration.saved' : 'configuration.saveError'),
        timeout: ok ? 1400 : 3000,
    })
}

async function persist(value: string | null, action: PersistAction): Promise<boolean> {
    if (!canEdit.value || saving.value) return false
    savingAction.value = action
    try {
        await paramsStore.updateParam(field.name, value, false, action === 'save' ? undefined : action)
        draft.value = paramsStore.getParamByName(field.name)?.value ?? ''
        notify(true)
        return true
    } catch {
        draft.value = currentValue.value
        notify(false)
        return false
    } finally {
        savingAction.value = null
    }
}

function save(): void {
    void persist(draft.value, 'save')
}

function keepCustom(): void {
    void persist(currentValue.value, 'keep_custom')
}

function openUseDefaultDialog(): void {
    useDefaultDialog.value = true
}

async function useDefault(): Promise<void> {
    if (await persist(null, 'use_default')) useDefaultDialog.value = false
}
</script>

<style scoped>
.prompt-editor {
    background: color-mix(in srgb, var(--q-primary) 2%, transparent);
}

.prompt-editor__conflict {
    border: 1px solid rgba(245, 124, 0, 0.35);
}

.prompt-editor__diff {
    border: 1px solid rgba(0, 0, 0, 0.12);
    border-radius: 6px;
    overflow: hidden;
}

.prompt-editor__diff > .row {
    padding: 8px 12px 0;
}

.prompt-editor__diff-lines {
    margin: 0;
    padding: 8px 0 12px;
    max-height: 420px;
    overflow: auto;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px;
    line-height: 1.55;
}

.prompt-editor__diff-line {
    display: block;
    min-width: max-content;
    padding: 0 12px;
    white-space: pre-wrap;
}

.prompt-editor__diff-line--added {
    background: rgba(33, 186, 69, 0.12);
}

.prompt-editor__diff-line--removed {
    background: rgba(193, 0, 21, 0.11);
}

.prompt-editor__diff-marker {
    display: inline-block;
    width: 22px;
    user-select: none;
}

.prompt-editor__dialog {
    width: min(520px, calc(100vw - 32px));
}

body.body--dark .prompt-editor__diff {
    border-color: rgba(255, 255, 255, 0.16);
}

@media (max-width: 1023px) {
    .prompt-editor :deep(.q-banner__actions) {
        padding-left: 0;
        padding-top: 12px;
    }
}
</style>
