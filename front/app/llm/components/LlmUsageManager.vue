<template>
    <section class="llm-usage-manager">
        <q-card flat bordered class="profile-panel">
            <q-card-section class="profile-banner">
                <q-avatar color="primary" text-color="white" icon="tune" size="36px" />
                <div class="profile-banner__select">
                    <q-select
                        v-model="selectedProfileId"
                        :options="profileOptions"
                        :label="t('llm.profileBannerLabel')"
                        option-value="id"
                        option-label="label"
                        emit-value
                        map-options
                        outlined
                        dense
                        :loading="profileStore.loading"
                        :disable="renamingProfile"
                        class="profile-select"
                    />
                    <div v-if="selectedProfile" class="text-caption q-mt-xs">
                        {{ t('llm.profileApiCode') }}: <code>{{ selectedProfile.code }}</code>
                    </div>
                </div>
                <q-chip
                    v-if="currentProfileLabel !== null"
                    dense
                    outline
                    color="primary"
                    class="profile-current-chip"
                >
                    {{ t('llm.profileCurrentBadge', { label: currentProfileLabel }) }}
                </q-chip>
                <div class="profile-banner__actions">
                    <template v-if="renamingProfile">
                        <q-input
                            v-model="draftRenameLabel"
                            :label="t('llm.profileLabelField')"
                            outlined
                            dense
                            maxlength="100"
                            autofocus
                            class="profile-rename-input"
                            @keyup.enter="onRenameSave"
                            @keyup.esc="onRenameCancel"
                        />
                        <q-btn
                            flat
                            round
                            dense
                            color="positive"
                            icon="check"
                            :disable="!draftRenameLabel.trim()"
                            :loading="profileSaving"
                            @click="onRenameSave"
                        />
                        <q-btn
                            flat
                            round
                            dense
                            color="grey-8"
                            icon="close"
                            @click="onRenameCancel"
                        />
                    </template>
                    <template v-else>
                        <q-btn
                            flat
                            round
                            dense
                            color="primary"
                            icon="add"
                            :disable="!canEdit || profileStore.loading"
                            @click="openProfileDialog"
                        >
                            <q-tooltip>{{ t('llm.profileAdd') }}</q-tooltip>
                        </q-btn>
                        <q-btn
                            flat
                            round
                            dense
                            color="primary"
                            icon="edit"
                            :disable="!canEdit || selectedProfileId === null || profileStore.loading"
                            @click="startRename"
                        >
                            <q-tooltip>{{ t('llm.profileEdit') }}</q-tooltip>
                        </q-btn>
                        <q-btn
                            flat
                            round
                            dense
                            color="negative"
                            icon="delete"
                            :disable="!canEdit || selectedProfileId === null || profileStore.loading"
                            @click="onDeleteProfile"
                        >
                            <q-tooltip>{{ t('llm.profileDelete') }}</q-tooltip>
                        </q-btn>
                    </template>
                    <q-btn
                        v-if="showUseButton"
                        unelevated
                        dense
                        color="primary"
                        icon="play_arrow"
                        :label="t('llm.profileUse')"
                        :disable="!canEdit || profileStore.loading"
                        :loading="profileStore.applying"
                        @click="onUseProfile"
                    />
                </div>
                <div v-if="!initialLoading" class="usage-summary">
                    <span class="text-caption text-weight-bold">
                        {{ t('llm.usageConfiguredCount', { configured: configuredCount, total: modelRows.length }) }}
                    </span>
                    <span class="text-caption text-grey-7">{{ usageHintText }}</span>
                </div>
            </q-card-section>
            <q-expansion-item v-if="selectedProfile" icon="api" :label="t('llm.profileApiTitle')">
                <q-card-section class="q-pt-none">
                    <p class="text-caption">{{ t('llm.profileApiHint') }}</p>
                    <div><code>/api/profile/openai</code></div>
                    <div><code>/api/profile/anthropic</code></div>
                    <p class="q-mt-sm q-mb-none">
                        <code>{{ selectedProfile.code }}/text/high</code>
                    </p>
                </q-card-section>
            </q-expansion-item>
        </q-card>

        <q-dialog v-model="profileDialog">
            <q-card class="profile-dialog">
                <q-card-section class="galaris-dialog-title row items-center no-wrap">
                    <div class="text-h6 col">{{ t('llm.profileDialogCreateTitle') }}</div>
                    <q-btn
                        v-close-popup
                        flat
                        round
                        dense
                        icon="close"
                        :aria-label="t('llm.profileCancel')"
                    />
                </q-card-section>

                <q-card-section>
                    <q-input
                        v-model="draftLabel"
                        :label="t('llm.profileLabelField')"
                        outlined
                        dense
                        maxlength="100"
                        autofocus
                    />
                </q-card-section>

                <q-card-actions class="galaris-dialog-actions" align="right">
                    <q-btn v-close-popup flat color="grey-8" :label="t('llm.profileCancel')" />
                    <q-btn
                        unelevated
                        color="primary"
                        :label="t('llm.profileSave')"
                        :loading="profileSaving"
                        :disable="!draftLabel.trim()"
                        @click="onProfileDialogSave"
                    />
                </q-card-actions>
            </q-card>
        </q-dialog>

        <template v-if="initialLoading">
            <div class="usage-loading" aria-busy="true">
                <div v-for="index in PROFILE_MODEL_ROWS.length" :key="index" class="usage-loading__row">
                    <div><q-skeleton type="text" width="55%" /><q-skeleton type="text" /></div>
                    <q-skeleton type="QInput" />
                    <q-skeleton type="text" />
                </div>
            </div>
        </template>

        <template v-else>
            <div class="usage-groups">
                <section
                    v-for="group in modelGroups"
                    :key="group.key"
                    class="usage-category"
                    :aria-labelledby="`llm-usage-category-${group.key}`"
                >
                    <div
                        class="usage-category__header"
                        :style="{
                            '--usage-heading-light': solaireCss[group.color].light,
                            '--usage-heading-dark': solaireCss[group.color].dark,
                        }"
                    >
                        <q-icon :name="group.icon" size="20px" />
                        <h3
                            :id="`llm-usage-category-${group.key}`"
                            class="text-subtitle1 text-weight-bold usage-category__title"
                        >
                            {{ group.label }}
                        </h3>
                    </div>

                    <table class="usage-table" :aria-labelledby="`llm-usage-category-${group.key}`">
                        <colgroup>
                            <col class="usage-table__purpose" />
                            <col class="usage-table__model" />
                            <col class="usage-table__effort" />
                        </colgroup>
                        <thead>
                            <tr>
                                <th scope="col" class="text-grey-7">{{ t('llm.usageColumns.purpose') }}</th>
                                <th scope="col" class="text-grey-7">{{ t('llm.usageColumns.model') }}</th>
                                <th scope="col" class="text-grey-7">
                                    {{ t('llm.usageColumns.effort') }}
                                    <q-icon name="info_outline" size="14px" class="q-ml-xs" :tabindex="$q.screen.lt.md ? -1 : 0" :aria-label="t('llm.reasoningEffortHint')">
                                        <q-tooltip>{{ t('llm.reasoningEffortHint') }}</q-tooltip>
                                    </q-icon>
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr
                                v-for="row in group.rows"
                                :key="row.modelField"
                                class="usage-row"
                            >
                                <th scope="row" class="usage-copy">
                                    <div class="text-subtitle2 text-weight-bold usage-label">
                                        {{ row.label }}
                                    </div>
                                    <div class="text-caption text-grey-7 usage-description">
                                        {{ row.description }}
                                    </div>
                                </th>

                                <td class="usage-selector">
                                    <q-select
                                        :model-value="viewValues[row.modelField]"
                                        :options="optionsForRow(row.modelField)"
                                        :display-value="selectedModelLabel(row.modelField)"
                                        :aria-label="`${t('llm.usageModel')} — ${row.label}`"
                                        option-value="value"
                                        option-label="label"
                                        emit-value
                                        map-options
                                        outlined
                                        dense
                                        clearable
                                        hide-bottom-space
                                        options-dense
                                        :loading="savingField === row.modelField"
                                        :disable="!canEdit || savingField !== null"
                                        class="usage-select"
                                        @update:model-value="value => onModelChange(row.modelField, value)"
                                    >
                                        <template #no-option>
                                            <q-item>
                                                <q-item-section class="text-grey">
                                                    {{ t('llm.noCompatibleModel') }}
                                                </q-item-section>
                                            </q-item>
                                        </template>
                                    </q-select>
                                    <template v-if="row.modelField === 'decision_llm_id'">
                                        <div class="text-caption q-mt-xs">{{ t('llm.decisionTextModel', { dispatcher: selectedModelLabel('text_low_llm_id') ?? t('llm.unavailable'), dream: selectedModelLabel('text_ultra_low_llm_id') ?? t('llm.unavailable') }) }}</div>
                                        <q-checkbox
                                            :model-value="selectedProfile?.decision_fallback_policy !== 'disabled'"
                                            :label="t('llm.decisionFallback')"
                                            :disable="!canEdit || savingField !== null"
                                            @update:model-value="onDecisionFallbackChange"
                                        />
                                    </template>
                                </td>
                                <td class="usage-effort" :class="{ 'usage-effort--empty': row.reasoningField === null }">
                                    <div
                                        v-if="row.reasoningField !== null"
                                        class="reasoning-control"
                                    >
                                        <div class="reasoning-control__header">
                                            <span class="reasoning-control__mobile-label text-caption">
                                                {{ t('llm.reasoningEffort') }}
                                            </span>
                                            <span class="reasoning-control__value text-caption text-weight-medium">
                                                {{ reasoningLabel(reasoningDrafts[row.reasoningField]) }}
                                            </span>
                                        </div>
                                        <q-slider
                                            :model-value="reasoningDrafts[row.reasoningField]"
                                            :min="REASONING_LEVEL_MIN"
                                            :max="REASONING_LEVEL_MAX"
                                            :step="1"
                                            markers
                                            snap
                                            :color="reasoningDrafts[row.reasoningField] < 0 ? 'grey-7' : 'primary'"
                                            :aria-label="`${t('llm.reasoningEffort')} — ${row.label}`"
                                            :aria-valuetext="reasoningLabel(reasoningDrafts[row.reasoningField])"
                                            :disable="!canEdit || savingField !== null"
                                            @update:model-value="value => onReasoningDraft(row.reasoningField, value)"
                                            @change="value => onReasoningChange(row.modelField, row.reasoningField, value)"
                                        />
                                        <div class="reasoning-control__legend text-grey-7" aria-hidden="true">
                                            <span
                                                v-for="level in REASONING_LEVELS"
                                                :key="level.value"
                                                :class="{ 'text-weight-bold': reasoningDrafts[row.reasoningField] === level.value }"
                                            >
                                                {{ t(`llm.reasoningEfforts.${level.key}`) }}
                                            </span>
                                        </div>
                                    </div>
                                    <span v-else aria-hidden="true">—</span>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </section>
            </div>
        </template>
    </section>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { computed, onMounted, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useLLMProviderStore } from '../stores/llmProviderStore'
import { useLLMProfileStore } from '../stores/llmProfileStore'
import type {
    LlmProfile,
    LlmProfileUpdate,
    ReasoningEffort,
} from '../services/llmProfileService'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { solaireCss, type SolaireColor } from '@/core/util'

type ModelCategory = 'text' | 'image' | 'audio' | 'multimedia' | 'embedding' | 'decision'

// One row per model column of the llm_profiles table, grouped in display order.
const PROFILE_MODEL_ROWS = [
    { column: 'text_ultra_low_llm_id', category: 'text' },
    { column: 'text_low_llm_id', category: 'text' },
    { column: 'text_standard_llm_id', category: 'text' },
    { column: 'text_high_llm_id', category: 'text' },
    { column: 'document_llm_id', category: 'text' },
    { column: 'vision_llm_id', category: 'image' },
    { column: 'image_llm_id', category: 'image' },
    { column: 'transcription_llm_id', category: 'audio' },
    { column: 'audio_llm_id', category: 'multimedia' },
    { column: 'video_llm_id', category: 'multimedia' },
    { column: 'sound_generation_llm_id', category: 'multimedia' },
    { column: 'music_generation_llm_id', category: 'multimedia' },
    { column: 'video_generation_llm_id', category: 'multimedia' },
    { column: 'vector_llm_id', category: 'embedding' },
    { column: 'decision_llm_id', category: 'decision' },
] as const

type ModelField = typeof PROFILE_MODEL_ROWS[number]['column']
type ReasoningField =
    | 'text_ultra_low_reasoning_effort'
    | 'text_low_reasoning_effort'
    | 'text_standard_reasoning_effort'
    | 'text_high_reasoning_effort'
type EditableProfileField = ModelField | ReasoningField

const REASONING_FIELD_BY_MODEL: Partial<Record<ModelField, ReasoningField>> = {
    text_ultra_low_llm_id: 'text_ultra_low_reasoning_effort',
    text_low_llm_id: 'text_low_reasoning_effort',
    text_standard_llm_id: 'text_standard_reasoning_effort',
    text_high_llm_id: 'text_high_reasoning_effort',
}

const REASONING_LEVELS = [
    { value: -1, key: 'auto', effort: null },
    { value: 0, key: 'none', effort: 'none' },
    { value: 1, key: 'low', effort: 'low' },
    { value: 2, key: 'medium', effort: 'medium' },
    { value: 3, key: 'high', effort: 'high' },
    { value: 4, key: 'xhigh', effort: 'xhigh' },
    { value: 5, key: 'max', effort: 'max' },
] as const satisfies ReadonlyArray<{
    value: number
    key: string
    effort: ReasoningEffort | null
}>
const REASONING_LEVEL_MIN = REASONING_LEVELS[0].value
const REASONING_LEVEL_MAX = REASONING_LEVELS[REASONING_LEVELS.length - 1].value

interface ModelOption {
    label: string
    value: number
}

interface CategoryVisual {
    key: ModelCategory
    icon: string
    color: SolaireColor
}

const CATEGORY_VISUALS: readonly CategoryVisual[] = [
    { key: 'text', icon: 'subject', color: 'blue' },
    { key: 'image', icon: 'image', color: 'violet' },
    { key: 'audio', icon: 'graphic_eq', color: 'fuchsia' },
    { key: 'multimedia', icon: 'perm_media', color: 'orange' },
    { key: 'embedding', icon: 'hub', color: 'green' },
    { key: 'decision', icon: 'alt_route', color: 'blue' },
]

const TRANSCRIPTION_MODEL_FIELD: ModelField = 'transcription_llm_id'
const VISION_MODEL_FIELD: ModelField = 'vision_llm_id'
const DOCUMENT_MODEL_FIELD: ModelField = 'document_llm_id'
const AUDIO_MODEL_FIELD: ModelField = 'audio_llm_id'
const VIDEO_MODEL_FIELD: ModelField = 'video_llm_id'
const IMAGE_MODEL_FIELD: ModelField = 'image_llm_id'
const VECTOR_MODEL_FIELD: ModelField = 'vector_llm_id'
const TEXT_MODEL_FIELDS = new Set<ModelField>([
    'text_ultra_low_llm_id',
    'text_low_llm_id',
    'text_standard_llm_id',
    'text_high_llm_id',
])

const $q = useQuasar()
const { t } = useI18n()
const llmStore = useLLMProviderStore()
const profileStore = useLLMProfileStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))

const initialLoading = ref(true)
const savingField = ref<EditableProfileField | null>(null)
const reasoningDrafts = ref<Record<ReasoningField, number>>({
    text_ultra_low_reasoning_effort: REASONING_LEVEL_MIN,
    text_low_reasoning_effort: REASONING_LEVEL_MIN,
    text_standard_reasoning_effort: REASONING_LEVEL_MIN,
    text_high_reasoning_effort: REASONING_LEVEL_MIN,
})

// Model-profile banner state. The grid always edits the selected profile's
// own columns; "Use this profile" only makes a profile the current one.
const selectedProfileId = ref<number | null>(null)
const profileDialog = ref(false)
const draftLabel = ref('')
const profileSaving = ref(false)
const renamingProfile = ref(false)
const draftRenameLabel = ref('')

function usageLabel(modelField: ModelField): string {
    return t(`llm.profileUsages.${modelField}.label`)
}

function usageDescription(modelField: ModelField): string {
    return t(`llm.profileUsages.${modelField}.description`)
}

function toModelOption(llm: typeof llmStore.llms[number]): ModelOption {
    return {
        label: `${llm.label} (${llm.provider_name})`,
        value: llm.id,
    }
}

function supportsChat(llm: typeof llmStore.llms[number]): boolean {
    return llm.service_capabilities.includes('chat') || llm.primary_capability === 'chat'
}

const textLlmOptions = computed<ModelOption[]>(() => (
    llmStore.llms
        .filter(supportsChat)
        .map(toModelOption)
))

const embeddingLlmOptions = computed<ModelOption[]>(() => (
    llmStore.llms
        .filter(llm => llm.primary_capability === 'embedding')
        .map(toModelOption)
))

const transcriptionLlmOptions = computed<ModelOption[]>(() => (
    llmStore.llms.filter(llm => llm.input_audio).map(toModelOption)
))

const imageLlmOptions = computed<ModelOption[]>(() => (
    llmStore.llms.filter(llm => llm.output_image).map(toModelOption)
))

const visionLlmOptions = computed<ModelOption[]>(() => (
    llmStore.llms
        .filter(llm => llm.input_image && llm.output_text)
        .map(toModelOption)
))

const documentLlmOptions = computed<ModelOption[]>(() => (
    llmStore.llms
        .filter(llm => llm.input_file && llm.output_text)
        .map(toModelOption)
))

const audioLlmOptions = computed<ModelOption[]>(() => (
    llmStore.llms
        .filter(llm => llm.service_capabilities.includes('audio_understanding') || (supportsChat(llm) && llm.input_audio && llm.output_text))
        .map(toModelOption)
))

const videoLlmOptions = computed<ModelOption[]>(() => (
    llmStore.llms
        .filter(llm => llm.service_capabilities.includes('video_understanding') || (supportsChat(llm) && llm.input_video && llm.output_text))
        .map(toModelOption)
))

const profileOptions = computed(() => profileStore.profiles.map(profile => ({
    id: profile.id,
    label: profile.label,
})))

const selectedProfile = computed<LlmProfile | null>(() => (
    selectedProfileId.value === null
        ? null
        : profileStore.getProfileById(selectedProfileId.value) ?? null
))

// The values the grid displays: the selected profile's own columns. Browsing
// a non-current profile and editing it are the same thing now.
const viewValues = computed<Partial<Record<ModelField, number | null>>>(() => {
    const profile = selectedProfile.value
    const values: Partial<Record<ModelField, number | null>> = {}
    if (profile === null) return values
    for (const row of PROFILE_MODEL_ROWS) {
        values[row.column] = profile[row.column]
    }
    return values
})

const modelRows = computed(() => PROFILE_MODEL_ROWS.map(row => ({
    modelField: row.column,
    category: row.category,
    reasoningField: REASONING_FIELD_BY_MODEL[row.column] ?? null,
    configured: viewValues.value[row.column] != null,
    label: usageLabel(row.column),
    description: usageDescription(row.column),
})))

const modelGroups = computed(() => CATEGORY_VISUALS.map(category => ({
    ...category,
    label: t(`llm.profileUsageCategories.${category.key}`),
    rows: modelRows.value.filter(row => row.category === category.key),
})))

function reasoningLevel(effort: ReasoningEffort | null): number {
    return REASONING_LEVELS.find(level => level.effort === effort)?.value
        ?? REASONING_LEVEL_MIN
}

function reasoningLabel(level: number): string {
    const key = REASONING_LEVELS.find(item => item.value === level)?.key ?? 'auto'
    return t(`llm.reasoningEfforts.${key}`)
}

function onReasoningDraft(field: ReasoningField | null, value: number | null): void {
  if (field === null) return
    reasoningDrafts.value[field] = value ?? REASONING_LEVEL_MIN
}

watch(selectedProfile, profile => {
    for (const field of Object.values(REASONING_FIELD_BY_MODEL)) {
        if (field !== undefined) {
            reasoningDrafts.value[field] = reasoningLevel(profile?.[field] ?? null)
        }
    }
}, { immediate: true })

const configuredCount = computed(() => PROFILE_MODEL_ROWS.filter(
    row => viewValues.value[row.column] != null,
).length)

function optionsForRow(modelField: ModelField): ModelOption[] {
    if (modelField === 'decision_llm_id') {
        return llmStore.llms.filter(llm => llm.service_capabilities.includes('decision')).map(toModelOption)
    }
    if (modelField === TRANSCRIPTION_MODEL_FIELD) return transcriptionLlmOptions.value
    if (modelField === AUDIO_MODEL_FIELD) return audioLlmOptions.value
    if (modelField === 'sound_generation_llm_id') return llmStore.llms.filter(llm => llm.service_capabilities.includes('sound_generation')).map(toModelOption)
    if (modelField === 'music_generation_llm_id') return llmStore.llms.filter(llm => llm.service_capabilities.includes('music_generation')).map(toModelOption)
    if (modelField === 'video_generation_llm_id') return llmStore.llms.filter(llm => llm.service_capabilities.includes('video_generation')).map(toModelOption)
    if (modelField === VISION_MODEL_FIELD) return visionLlmOptions.value
    if (modelField === DOCUMENT_MODEL_FIELD) return documentLlmOptions.value
    if (modelField === VIDEO_MODEL_FIELD) return videoLlmOptions.value
    if (modelField === IMAGE_MODEL_FIELD) return imageLlmOptions.value
    if (modelField === VECTOR_MODEL_FIELD) return embeddingLlmOptions.value
    if (TEXT_MODEL_FIELDS.has(modelField)) return textLlmOptions.value
    return []
}

function selectedModelLabel(modelField: ModelField): string | undefined {
    const id = viewValues.value[modelField]
    if (id == null) return undefined
    // A saved model may no longer be eligible for this usage. Its name still
    // comes from the full catalogue, independently of the selectable options.
    const model = llmStore.llms.find(llm => llm.id === id)
    return model ? toModelOption(model).label : t('llm.unavailable')
}

// =============================================================================
// Model profiles.
// =============================================================================

// Banner badge; null while no profile is current.
const currentProfileLabel = computed(() => profileStore.currentProfile?.label ?? null)

// "Use this profile" only sets the current-profile pointer, so it makes sense
// only when the selected profile is not already the current one.
const showUseButton = computed(() => (
    selectedProfileId.value !== null
    && selectedProfileId.value !== profileStore.currentProfileId
))

// The grid never locks, whatever the selected profile: the hint stays generic.
const usageHintText = computed(() => t('llm.usageHint'))

function apiErrorDetail(error: unknown, fallback: string): string {
    const detail = (error as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail
    return typeof detail === 'string' && detail ? detail : fallback
}

function startRename(): void {
    if (!canEdit.value || selectedProfileId.value === null) return
    draftRenameLabel.value = selectedProfile.value?.label ?? ''
    renamingProfile.value = true
}

function onRenameCancel(): void {
    renamingProfile.value = false
    draftRenameLabel.value = ''
}

async function onRenameSave(): Promise<void> {
    const label = draftRenameLabel.value.trim()
    if (!canEdit.value || selectedProfileId.value === null || !label) return
    profileSaving.value = true
    try {
        const profile = await profileStore.updateProfile(selectedProfileId.value, { label })
        renamingProfile.value = false
        $q.notify({
            type: 'positive',
            message: t('llm.profileRenamed', { label: profile.label }),
            timeout: 2000,
        })
    } catch (error) {
        $q.notify({
            type: 'negative',
            message: apiErrorDetail(error, t('llm.profileRenameError')),
            timeout: 3000,
        })
    } finally {
        profileSaving.value = false
    }
}

function openProfileDialog(): void {
    if (!canEdit.value) return
    draftLabel.value = ''
    profileDialog.value = true
}

async function onProfileDialogSave(): Promise<void> {
    profileSaving.value = true
    try {
        const profile = await profileStore.createProfile({ label: draftLabel.value.trim() })
        selectedProfileId.value = profile.id
        $q.notify({
            type: 'positive',
            message: t('llm.profileCreated', { label: profile.label }),
            timeout: 2000,
        })
        profileDialog.value = false
    } catch (error) {
        $q.notify({
            type: 'negative',
            message: apiErrorDetail(error, t('llm.profileSaveError')),
            timeout: 3000,
        })
    } finally {
        profileSaving.value = false
    }
}

async function onDeleteProfile(): Promise<void> {
    const profile = selectedProfile.value
    if (!canEdit.value || profile === null) return
    showConfirmationDialog({
        title: t('llm.profileDeleteConfirmTitle'),
        message: t('llm.profileDeleteConfirm', { label: profile.label }),
        cancel: t('llm.profileCancel'),
        ok: { label: t('llm.profileDelete'), color: 'negative', flat: true },
    }).onOk(async () => {
        try {
            renamingProfile.value = false
            await profileStore.deleteProfile(profile.id)
            // Re-read the list: deleting the current profile makes the back
            // point the current-profile parameter at the fallback.
            await profileStore.fetchProfiles()
            selectedProfileId.value = profileStore.currentProfileId
                ?? profileStore.profiles[0]?.id
                ?? null
            $q.notify({
                type: 'positive',
                message: t('llm.profileDeleted', { label: profile.label }),
                timeout: 2000,
            })
        } catch (error) {
            $q.notify({
                type: 'negative',
                message: apiErrorDetail(error, t('llm.profileDeleteError')),
                timeout: 3000,
            })
        }
    })
}

async function onUseProfile(): Promise<void> {
    if (!canEdit.value || selectedProfileId.value === null) return
    const label = selectedProfile.value?.label ?? ''
    try {
        await profileStore.useProfile(selectedProfileId.value)
        // Pointer only: the badge follows from the store and the grid already
        // displays this profile's columns.
        $q.notify({
            type: 'positive',
            message: t('llm.profileUsed', { label }),
            timeout: 2500,
        })
    } catch (error) {
        $q.notify({
            type: 'negative',
            message: apiErrorDetail(error, t('llm.profileUseError')),
            timeout: 3000,
        })
    }
}

async function onModelChange(modelField: ModelField, value: number | null): Promise<void> {
    if (!canEdit.value || selectedProfileId.value === null) return

    const update = {} as LlmProfileUpdate
    update[modelField] = value

    savingField.value = modelField
    try {
        await profileStore.saveProfileValues(selectedProfileId.value, update)
        $q.notify({
            type: 'positive',
            message: t('llm.profileUsageUpdated', { name: usageLabel(modelField) }),
            timeout: 2000,
        })
    } catch {
        $q.notify({
            type: 'negative',
            message: t('llm.profileUsageUpdateError', { name: usageLabel(modelField) }),
            timeout: 3000,
        })
    } finally {
        savingField.value = null
    }
}

async function onDecisionFallbackChange(enabled: boolean): Promise<void> {
    if (!canEdit.value || selectedProfileId.value === null) return
    savingField.value = 'decision_llm_id'
    try {
        await profileStore.saveProfileValues(selectedProfileId.value, {
            decision_fallback_policy: enabled ? 'text_on_failure' : 'disabled',
        })
    } catch {
        $q.notify({ type: 'negative', message: t('llm.profileUsageUpdateError', { name: usageLabel('decision_llm_id') }) })
    } finally {
        savingField.value = null
    }
}

async function onReasoningChange(
    modelField: ModelField,
    reasoningField: ReasoningField | null,
    value: number | null,
): Promise<void> {
    if (!canEdit.value || selectedProfileId.value === null || reasoningField === null) return
    const level = value ?? REASONING_LEVEL_MIN
    const effort = REASONING_LEVELS.find(item => item.value === level)?.effort ?? null
    const update = {} as LlmProfileUpdate
    update[reasoningField] = effort

    savingField.value = reasoningField
    try {
        await profileStore.saveProfileValues(selectedProfileId.value, update)
        $q.notify({
            type: 'positive',
            message: t('llm.reasoningEffortUpdated', { name: usageLabel(modelField) }),
            timeout: 2000,
        })
    } catch {
        reasoningDrafts.value[reasoningField] = reasoningLevel(
            selectedProfile.value?.[reasoningField] ?? null,
        )
        $q.notify({
            type: 'negative',
            message: t('llm.reasoningEffortUpdateError', { name: usageLabel(modelField) }),
            timeout: 3000,
        })
    } finally {
        savingField.value = null
    }
}

onMounted(async () => {
    try {
        await llmStore.fetchLLMs()
        try {
            await profileStore.fetchProfiles()
        } catch {
            $q.notify({
                type: 'negative',
                message: t('llm.profileLoadError'),
                timeout: 3000,
            })
        }
        // Open the current profile by default; the grid reads its columns.
        selectedProfileId.value = profileStore.currentProfileId
            ?? profileStore.profiles[0]?.id
            ?? null
    } finally {
        initialLoading.value = false
    }
})
</script>

<style scoped>
.llm-usage-manager {
    min-width: 0;
}

.usage-summary {
    display: flex;
    flex: 0 0 100%;
    flex-wrap: wrap;
    gap: 4px 12px;
    padding-left: 44px;
}

.profile-panel {
    margin-bottom: 16px;
    border-left: 4px solid var(--q-primary);
    border-radius: 12px;
}

.profile-banner {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 8px;
}

.profile-banner__select {
    flex: 1;
    min-width: min(220px, 100%);
    max-width: 360px;
}

.profile-select {
    width: 100%;
}

.profile-banner__actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    margin-left: auto;
}

.profile-rename-input {
    min-width: 200px;
    width: 260px;
}

.profile-dialog {
    width: min(420px, 94vw);
}

.usage-loading__row {
    display: grid;
    grid-template-columns: 36fr 34fr 30fr;
    gap: 24px;
    padding: 12px;
}

.usage-groups {
    display: flex;
    flex-direction: column;
    gap: 20px;
}

.usage-category {
    min-width: 0;
    border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
    border-radius: 8px;
    overflow: hidden;
}

.usage-category__header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: var(--usage-heading-light);
}

body.body--dark .usage-category__header {
    background: var(--usage-heading-dark);
}

.usage-category__title {
    margin: 0;
    color: inherit;
}

.usage-table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
}

.usage-table__purpose { width: 36%; }
.usage-table__model { width: 34%; }
.usage-table__effort { width: 30%; }

.usage-table th,
.usage-table td {
    padding: 10px 14px;
    text-align: left;
    vertical-align: middle;
    border-top: 1px solid color-mix(in srgb, currentColor 12%, transparent);
}

.usage-table thead th {
    padding-top: 7px;
    padding-bottom: 7px;
    font-size: 12px;
    font-weight: 500;
}

.usage-row:focus-within {
    background: color-mix(in srgb, var(--q-primary) 4%, transparent);
}

.usage-copy {
    min-width: 0;
}

.usage-label {
    line-height: 1.3;
}

.usage-description {
    margin-top: 3px;
    font-weight: 400;
    line-height: 1.4;
    white-space: normal;
    overflow-wrap: anywhere;
}

.usage-select {
    width: 100%;
}

.reasoning-control {
    min-width: 0;
    padding: 0 4px;
}

.reasoning-control__header {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
}

.reasoning-control__value {
    white-space: nowrap;
}

.reasoning-control__mobile-label {
    display: none;
}

.reasoning-control__legend {
    display: grid;
    grid-template-columns: minmax(max-content, 1fr) repeat(5, minmax(0, 1fr)) minmax(max-content, 1fr);
    gap: 2px;
    font-size: 10px;
    line-height: 1.2;
    text-align: center;
    overflow-wrap: anywhere;
}

.reasoning-control__legend span:first-child {
    text-align: left;
}

.reasoning-control__legend span:last-child {
    text-align: right;
}

@media (max-width: 1023px) {
    .usage-table,
    .usage-table tbody {
        display: block;
    }

    .usage-table colgroup {
        display: none;
    }

    .usage-table thead {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip-path: inset(50%);
    }

    .usage-row {
        display: grid;
        grid-template-columns: minmax(0, 1fr);
        padding: 12px 14px;
        gap: 10px;
        border-top: 1px solid color-mix(in srgb, currentColor 12%, transparent);
    }

    .usage-table th,
    .usage-table td {
        display: block;
        min-width: 0;
        padding: 0;
        border: 0;
    }

    .usage-table .usage-effort--empty {
        display: none;
    }

    .reasoning-control__mobile-label {
        display: inline;
    }

    .reasoning-control__header {
        justify-content: space-between;
    }

    .usage-summary {
        padding-left: 0;
    }
}
</style>
