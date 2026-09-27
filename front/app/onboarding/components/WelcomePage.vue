<template>
  <q-page class="welcome-page q-pa-md">
    <div class="welcome-shell">
      <div v-if="!authStore.isAuthenticated" class="welcome-state">
        <q-icon name="lock_open" size="52px" color="primary" />
        <h1>{{ t('onboarding.authentication.title') }}</h1>
        <p>{{ t('onboarding.authentication.description') }}</p>
        <q-btn
          unelevated
          no-caps
          color="primary"
          icon="login"
          :label="t('onboarding.authentication.action')"
          to="/user/login"
        />
      </div>

      <div v-else-if="onboardingStore.error" class="welcome-state">
        <q-icon name="cloud_off" size="52px" color="negative" />
        <h1>{{ t('onboarding.error.title') }}</h1>
        <p>{{ t('onboarding.error.description') }}</p>
        <q-btn
          outline
          no-caps
          color="primary"
          icon="refresh"
          :label="t('onboarding.actions.retry')"
          @click="refresh"
        />
      </div>

      <div v-else-if="onboardingStore.loading || !onboardingStore.isLoaded" class="welcome-state">
        <q-spinner-orbit color="primary" size="56px" />
        <h1>{{ t('onboarding.loading') }}</h1>
      </div>

      <template v-else>
        <section class="welcome-hero">
          <div class="welcome-hero__content">
            <div class="welcome-eyebrow">
              <q-icon name="auto_awesome" />
              {{ t('onboarding.eyebrow') }}
            </div>
            <h1>{{ t('onboarding.title') }}</h1>
            <p>{{ t('onboarding.description') }}</p>

            <div class="welcome-progress">
              <div class="welcome-progress__labels">
                <span>{{ t('onboarding.progress') }}</span>
                <strong>{{ t('onboarding.progressCount', { count: requiredCompleted, total: requiredTotal }) }}</strong>
              </div>
              <q-linear-progress
                rounded
                size="10px"
                color="positive"
                track-color="white"
                :value="requiredProgress"
              />
            </div>
          </div>

          <div class="welcome-hero__mark" aria-hidden="true">
            <q-icon :name="mandatoryReady ? 'rocket_launch' : 'route'" />
          </div>
        </section>

        <q-banner v-if="mandatoryReady" rounded class="ready-banner">
          <template #avatar>
            <q-icon name="task_alt" color="positive" />
          </template>
          <div class="text-weight-bold">{{ t('onboarding.ready.title') }}</div>
          <div class="text-caption">{{ t('onboarding.ready.description') }}</div>
          <template #action>
            <q-btn
              flat
              no-caps
              color="positive"
              icon-right="arrow_forward"
              :label="t('onboarding.actions.home')"
              to="/"
            />
          </template>
        </q-banner>

        <section :aria-label="t('onboarding.summary.title')">
          <q-stepper
            v-model="activeStep"
            flat
            alternative-labels
            header-nav
            active-icon="none"
            done-icon="none"
            color="primary"
            class="welcome-stepper"
          >
            <q-step
              v-for="step in steps"
              :key="step.key"
              :name="step.name"
              :title="t(`onboarding.steps.${step.key}.title`)"
              :caption="statusFor(step).label"
              :prefix="step.name"
              :icon="step.icon"
              :done="step.complete === true"
            >
              <article class="step-content" :aria-label="t(`onboarding.steps.${step.key}.title`)">
                <div class="step-content__header">
                  <div>
                    <div class="step-number">
                      {{ t('onboarding.stepNumber', { current: step.name, total: steps.length }) }}
                    </div>
                    <h2>{{ t(`onboarding.steps.${step.key}.title`) }}</h2>
                  </div>
                  <q-chip
                    dense
                    :class="`step-status--${statusFor(step).tone}`"
                    :icon="statusFor(step).icon"
                  >
                    {{ statusFor(step).label }}
                  </q-chip>
                </div>

                <p class="step-lead">{{ t(`onboarding.steps.${step.key}.description`) }}</p>

                <div v-if="step.key === 'language'" class="welcome-language">
                  <div v-if="!canAccessParams" class="text-caption">{{ t('onboarding.permissionRequired') }}</div>
                  <div v-else-if="languageLoading" role="status">
                    <q-spinner color="primary" class="q-mr-sm" />{{ t('common.loading') }}
                  </div>
                  <q-banner v-else-if="languageLoadError" rounded>
                    {{ t('onboarding.error.description') }}
                    <template #action>
                      <q-btn flat no-caps :label="t('common.retry')" @click="loadLanguage" />
                    </template>
                  </q-banner>
                  <div v-else-if="configuredLanguage" class="welcome-language__saved" role="status">
                    <q-icon name="check_circle" color="positive" size="20px" />
                    <strong>{{ configuredLanguage }}</strong>
                  </div>
                  <div v-else :inert="paramsStore.loading" class="welcome-language__field">
                    <SettingsFields :fields="defaultLanguageFields" />
                  </div>
                </div>

                <div v-if="step.tipKeys.length" class="step-tips">
                  <div class="step-tips__title">
                    <q-icon name="tips_and_updates" />
                    {{ t('onboarding.tipsTitle') }}
                  </div>
                  <ul>
                    <li v-for="tip in step.tipKeys" :key="tip">{{ t(tip) }}</li>
                  </ul>
                </div>

                <q-banner v-if="step.key !== 'language' && !step.canEdit && !step.complete" rounded class="permission-banner">
                  <template #avatar><q-icon name="admin_panel_settings" /></template>
                  {{ t('onboarding.permissionRequired') }}
                </q-banner>

                <div v-if="step.key !== 'language'" class="step-actions">
                  <q-btn
                    v-if="step.canEdit && step.route"
                    unelevated
                    no-caps
                    color="primary"
                    icon-right="open_in_new"
                    :label="t(`onboarding.steps.${step.key}.${step.complete ? 'reviewAction' : 'action'}`)"
                    :to="step.route"
                  />
                  <q-btn
                    outline
                    no-caps
                    color="primary"
                    icon="refresh"
                    :label="t('onboarding.actions.refresh')"
                    @click="refresh"
                  />
                </div>

                <q-separator />

                <div class="step-navigation">
                  <q-btn
                    v-if="step.name > 1"
                    flat
                    no-caps
                    icon="arrow_back"
                    :label="t('onboarding.actions.previous')"
                    @click="activeStep = step.name - 1"
                  />
                  <span />
                  <q-btn
                    v-if="step.name < steps.length"
                    flat
                    no-caps
                    color="primary"
                    icon-right="arrow_forward"
                    :label="t('onboarding.actions.next')"
                    class="step-navigation__next"
                    @click="activeStep = step.name + 1"
                  />
                </div>
              </article>
            </q-step>
          </q-stepper>
        </section>
      </template>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { languageFields, SettingsFields, useParamsStore } from '@/core/params'
import { useAuthStore } from '@/core/user'
import { useOnboardingStore } from '../stores/onboardingStore'

type StepKey = 'language' | 'llm' | 'agent' | 'tools' | 'connections' | 'skills' | 'processes'

interface SetupStep {
  name: number
  key: StepKey
  icon: string
  route: string | null
  required: boolean
  complete: boolean | null
  canEdit: boolean
  tipKeys: string[]
}

interface StepStatus {
  label: string
  tone: 'green' | 'gray' | 'red' | 'orange'
  icon: string
}

const { t } = useI18n()
const authStore = useAuthStore()
const onboardingStore = useOnboardingStore()
const privilegeStore = usePrivilegeStore()
const paramsStore = useParamsStore()
const canAccessParams = computed(() => authStore.isAuthenticated && privilegeStore.hasPrivilege(privileges.PARAMS_ACCESS))
const defaultLanguageFields = languageFields.filter(field => field.name === 'DEFAULT_LANGUAGE')
const configuredLanguage = computed(() => {
  const value = paramsStore.getParamValue('DEFAULT_LANGUAGE')
  if (!value?.trim()) return ''
  const option = defaultLanguageFields[0]?.options?.find(item => item.value === value)
  return option ? t(option.labelKey) : value
})
const languageLoading = ref(false)
const languageLoadError = ref(false)
const activeStep = ref(1)

async function loadLanguage(): Promise<void> {
  languageLoading.value = true
  languageLoadError.value = false
  await paramsStore.fetchParams(true)
  languageLoadError.value = Boolean(paramsStore.error)
  languageLoading.value = false
}

watch(canAccessParams, allowed => {
  if (allowed) void loadLanguage()
}, { immediate: true })

// Only persisted values update onboarding; failed saves leave Welcome visible.
watch(
  [languageLoading, languageLoadError, () => paramsStore.getParamValue('DEFAULT_LANGUAGE'), canAccessParams],
  ([loading, failed, value, allowed]) => {
    if (allowed && !loading && !failed && value !== null) {
      onboardingStore.languageConfigured = Boolean(value.trim())
    }
  },
)

const steps = computed<SetupStep[]>(() => [
  {
    name: 1,
    key: 'language',
    icon: 'translate',
    route: null,
    required: true,
    complete: onboardingStore.languageConfigured === true,
    canEdit: canAccessParams.value && privilegeStore.hasPrivilege(privileges.PARAMS_EDIT),
    tipKeys: [],
  },
  {
    name: 2,
    key: 'llm',
    icon: 'smart_toy',
    route: '/llm?tab=providers',
    required: true,
    complete: onboardingStore.llmProvider?.has_data ?? false,
    canEdit: onboardingStore.llmProvider?.has_privilege ?? false,
    tipKeys: [
      'onboarding.steps.llm.tipProvider',
      'onboarding.steps.llm.tipModel',
      'onboarding.steps.llm.tipTest',
    ],
  },
  {
    name: 3,
    key: 'agent',
    icon: 'support_agent',
    route: '/agent',
    required: true,
    complete: onboardingStore.agents?.has_data ?? false,
    canEdit: onboardingStore.agents?.has_privilege ?? false,
    tipKeys: [
      'onboarding.steps.agent.tipIdentity',
      'onboarding.steps.agent.tipModel',
      'onboarding.steps.agent.tipRole',
    ],
  },
  {
    name: 4,
    key: 'connections',
    icon: 'hub',
    route: '/tools?tab=connections',
    required: false,
    complete: onboardingStore.connections?.has_data ?? false,
    canEdit: onboardingStore.connections?.has_privilege ?? false,
    tipKeys: [
      'onboarding.steps.connections.tipChannels',
      'onboarding.steps.connections.tipAgent',
      'onboarding.steps.connections.tipSecrets',
    ],
  },
  {
    name: 5,
    key: 'tools',
    icon: 'construction',
    route: '/tools',
    required: false,
    complete: onboardingStore.tools?.has_data ?? false,
    canEdit: onboardingStore.tools?.has_privilege ?? false,
    tipKeys: [
      'onboarding.steps.tools.tipChoose',
      'onboarding.steps.tools.tipRights',
      'onboarding.steps.tools.tipLater',
    ],
  },
  {
    name: 6,
    key: 'skills',
    icon: 'psychology',
    route: '/skill',
    required: false,
    complete: onboardingStore.skills?.has_data ?? false,
    canEdit: onboardingStore.skillsAccess,
    tipKeys: [
      'onboarding.steps.skills.tipChoose',
      'onboarding.steps.skills.tipAssign',
      'onboarding.steps.skills.tipEvolve',
    ],
  },
  {
    name: 7,
    key: 'processes',
    icon: 'account_tree',
    route: '/process',
    required: false,
    complete: onboardingStore.processes?.has_data ?? false,
    canEdit: onboardingStore.processesAccess,
    tipKeys: [
      'onboarding.steps.processes.tipRepeatable',
      'onboarding.steps.processes.tipTools',
      'onboarding.steps.processes.tipObserve',
    ],
  },
])

const requiredSteps = computed(() => steps.value.filter(step => step.required))
const requiredCompleted = computed(() => requiredSteps.value.filter(step => step.complete === true).length)
const requiredTotal = computed(() => requiredSteps.value.length)
const requiredProgress = computed(() => requiredCompleted.value / requiredTotal.value)
const mandatoryReady = computed(() => requiredCompleted.value === requiredTotal.value)

function statusFor(step: SetupStep): StepStatus {
  if (step.complete === true) {
    return {
      label: t('onboarding.status.configured'),
      tone: 'green',
      icon: 'check_circle',
    }
  }
  if (!step.canEdit) {
    return {
      label: t('onboarding.status.restricted'),
      tone: 'gray',
      icon: 'lock',
    }
  }
  if (step.required) {
    return {
      label: t('onboarding.status.required'),
      tone: 'red',
      icon: 'priority_high',
    }
  }
  return {
    label: t('onboarding.status.recommended'),
    tone: 'orange',
    icon: 'lightbulb',
  }
}

function refresh(): void {
  void onboardingStore.fetchOverview()
  if (canAccessParams.value) void loadLanguage()
}
</script>

<style scoped>
.welcome-page {
  min-height: 100vh;
  background:
    radial-gradient(circle at 12% 6%, rgba(80, 124, 255, 0.1), transparent 30%),
    radial-gradient(circle at 88% 14%, rgba(139, 92, 246, 0.08), transparent 27%);
}

.welcome-shell {
  width: min(1180px, 100%);
  margin: 0 auto;
}

.welcome-state {
  display: flex;
  min-height: min(72vh, 720px);
  flex-direction: column;
  gap: 14px;
  align-items: center;
  justify-content: center;
  color: #64718b;
  text-align: center;
}

.welcome-state h1 {
  margin: 8px 0 0;
  color: #263652;
  font-size: clamp(1.55rem, 3vw, 2.2rem);
}

.welcome-state p {
  max-width: 540px;
  margin: 0 0 8px;
  line-height: 1.65;
}

.welcome-hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 28px;
  overflow: hidden;
  margin: 8px 0 20px;
  padding: clamp(26px, 5vw, 50px);
  color: white;
  border-radius: 28px;
  background-image:
    linear-gradient(90deg, rgba(2, 8, 24, 0.74) 0%, rgba(2, 8, 24, 0.56) 62%, rgba(2, 8, 24, 0.34) 100%),
    url('/background.jpg');
  background-repeat: no-repeat, repeat;
  background-position: center, center;
  box-shadow: 0 20px 52px rgba(49, 71, 140, 0.22);
}

.welcome-hero::after {
  position: absolute;
  right: -90px;
  bottom: -150px;
  width: 360px;
  height: 360px;
  border: 70px solid rgba(255, 255, 255, 0.07);
  border-radius: 50%;
  content: '';
}

.welcome-hero__content {
  position: relative;
  z-index: 1;
  max-width: 760px;
}

.welcome-eyebrow {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 14px;
  color: rgba(255, 255, 255, 0.82);
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}

.welcome-hero h1 {
  margin: 0;
  font-size: clamp(2rem, 5vw, 3.55rem);
  font-weight: 850;
  line-height: 1.05;
  letter-spacing: -0.035em;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.72);
}

.welcome-hero p {
  max-width: 680px;
  margin: 18px 0 0;
  color: #fff;
  font-size: clamp(0.95rem, 1.8vw, 1.12rem);
  line-height: 1.65;
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.78);
}

.welcome-hero__mark {
  position: relative;
  z-index: 1;
  display: grid;
  width: clamp(96px, 13vw, 150px);
  height: clamp(96px, 13vw, 150px);
  align-self: center;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 38px;
  background: rgba(255, 255, 255, 0.1);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16);
  backdrop-filter: blur(8px);
}

.welcome-hero__mark .q-icon {
  font-size: clamp(48px, 7vw, 78px);
}

.welcome-progress {
  max-width: 470px;
  margin-top: 28px;
}

.welcome-progress__labels {
  display: flex;
  justify-content: space-between;
  margin-bottom: 9px;
  color: rgba(255, 255, 255, 0.78);
  font-size: 0.73rem;
}

.welcome-progress__labels strong {
  color: white;
}

.ready-banner {
  margin-bottom: 20px;
  color: #1d6758;
  border: 1px solid #bce7db;
  background: #f0fbf7;
}

.welcome-stepper {
  --step-text: #292c30;
  --step-surface: var(--solaire-gray-light);
  --step-selected: var(--solaire-blue-light);
  --step-success: var(--solaire-green-light);
  --step-warning: var(--solaire-orange-light);
  --step-required: var(--solaire-red-light);
  overflow: hidden;
  border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
  border-radius: 22px;
}

.welcome-stepper :deep(.q-stepper__header) {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(140px, 100%), 1fr));
}

.welcome-stepper :deep(.q-stepper__tab) {
  min-width: 0;
  padding: 24px 10px;
}

.welcome-stepper :deep(.q-stepper__label) {
  max-width: 100%;
  overflow-wrap: anywhere;
}

.welcome-stepper :deep(.q-stepper__tab--active) {
  background: var(--step-selected);
}

.welcome-stepper :deep(.q-stepper__title) {
  color: var(--step-text);
  font-size: 0.85rem;
  line-height: 1.4;
}

.welcome-stepper :deep(.q-stepper__caption) {
  margin-top: 4px;
  color: var(--step-text);
  opacity: 0.75;
}

.welcome-stepper :deep(.q-stepper__dot) {
  background: var(--solaire-gray-accent);
}

.welcome-stepper :deep(.q-stepper__tab--done .q-stepper__dot) {
  background: var(--solaire-green-accent);
}

.welcome-stepper :deep(.q-stepper__tab--active .q-stepper__dot) {
  background: var(--solaire-blue-accent);
}

.welcome-stepper :deep(.q-stepper__tab:focus-visible) {
  outline: 2px solid var(--solaire-blue-accent);
  outline-offset: -3px;
}

.welcome-language {
  margin-bottom: 24px;
}

.welcome-language__saved {
  display: flex;
  align-items: center;
  gap: 12px;
}

.welcome-language__field {
  max-width: 480px;
}

.step-content {
  padding: clamp(2px, 1vw, 12px) clamp(0px, 2vw, 18px) 4px;
}

.step-content__header {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
}

.step-number {
  margin-bottom: 6px;
  font-size: 0.75rem;
  opacity: 0.7;
}

.step-content h2 {
  margin: 0;
  font-size: clamp(1.35rem, 2.4vw, 1.8rem);
}

.step-lead {
  max-width: 720px;
  margin: 16px 0 20px;
  font-size: 0.95rem;
  line-height: 1.65;
}

.step-tips {
  margin-bottom: 20px;
  padding: 18px 20px;
  border-radius: 16px;
  background: var(--step-surface);
}

.step-tips__title {
  display: flex;
  gap: 8px;
  align-items: center;
  font-weight: 600;
}

.step-tips ul {
  display: grid;
  gap: 8px;
  margin: 13px 0 0;
  padding-left: 20px;
  line-height: 1.55;
}

.permission-banner {
  margin-bottom: 18px;
  background: var(--step-warning);
}

.step-status--green { background: var(--step-success); }
.step-status--gray { background: var(--step-surface); }
.step-status--red { background: var(--step-required); }
.step-status--orange { background: var(--step-warning); }

.step-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 24px;
}

.step-navigation {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  padding-top: 12px;
}

.step-navigation__next {
  grid-column: 3;
}

body.body--dark .welcome-stepper {
  --step-text: #eeeef0;
  --step-surface: var(--solaire-gray-dark);
  --step-selected: var(--solaire-blue-dark);
  --step-success: var(--solaire-green-dark);
  --step-warning: var(--solaire-orange-dark);
  --step-required: var(--solaire-red-dark);
}

body.body--dark .welcome-state h1 {
  color: inherit;
}

body.body--dark .ready-banner {
  color: inherit;
  border-color: var(--solaire-green-accent);
  background: var(--solaire-green-dark);
}

@media (max-width: 650px) {
  .welcome-page { padding: 10px; }
  .welcome-hero {
    grid-template-columns: 1fr;
    padding: 26px 22px;
    border-radius: 22px;
  }
  .welcome-hero__mark { display: none; }
  .welcome-stepper :deep(.q-stepper__step-inner) { padding: 22px 16px; }
  .step-content__header { flex-direction: column; }
  .step-actions .q-btn { width: 100%; }
}
</style>
