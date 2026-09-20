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

        <div class="welcome-grid">
          <aside class="welcome-summary">
            <div class="welcome-summary__heading">
              <span>{{ t('onboarding.summary.title') }}</span>
              <small>{{ t('onboarding.summary.description') }}</small>
            </div>

            <button
              v-for="step in steps"
              :key="step.key"
              type="button"
              class="summary-step"
              :class="{ 'summary-step--active': activeStep === step.name }"
              @click="activeStep = step.name"
            >
              <span class="summary-step__icon" :class="`summary-step__icon--${step.tone}`">
                <q-icon :name="step.complete ? 'check' : step.icon" />
              </span>
              <span class="summary-step__copy">
                <strong>{{ t(`onboarding.steps.${step.key}.title`) }}</strong>
                <small>{{ step.required ? t('onboarding.required') : t('onboarding.optional') }}</small>
              </span>
              <q-icon name="chevron_right" class="summary-step__arrow" />
            </button>
          </aside>

          <q-stepper
            v-model="activeStep"
            flat
            animated
            color="primary"
            class="welcome-stepper"
          >
            <q-step
              v-for="step in steps"
              :key="step.key"
              :name="step.name"
              :title="t(`onboarding.steps.${step.key}.title`)"
              :caption="step.required ? t('onboarding.required') : t('onboarding.optional')"
              :icon="step.icon"
              :done="step.complete === true"
              :error="step.required && step.complete !== true"
            >
              <article class="step-content">
                <div class="step-content__header">
                  <div>
                    <div class="step-number">
                      {{ t('onboarding.stepNumber', { current: step.name, total: steps.length }) }}
                    </div>
                    <h2>{{ t(`onboarding.steps.${step.key}.title`) }}</h2>
                  </div>
                  <q-chip
                    dense
                    :color="statusFor(step).color"
                    :text-color="statusFor(step).textColor"
                    :icon="statusFor(step).icon"
                  >
                    {{ statusFor(step).label }}
                  </q-chip>
                </div>

                <p class="step-lead">{{ t(`onboarding.steps.${step.key}.description`) }}</p>

                <div class="step-tips">
                  <div class="step-tips__title">
                    <q-icon name="tips_and_updates" />
                    {{ t('onboarding.tipsTitle') }}
                  </div>
                  <ul>
                    <li v-for="tip in step.tipKeys" :key="tip">{{ t(tip) }}</li>
                  </ul>
                </div>

                <q-banner v-if="!step.canEdit && !step.complete" rounded class="permission-banner">
                  <template #avatar><q-icon name="admin_panel_settings" /></template>
                  {{ t('onboarding.permissionRequired') }}
                </q-banner>

                <div class="step-actions">
                  <q-btn
                    v-if="step.canEdit"
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
                    @click="activeStep = step.name + 1"
                  />
                </div>
              </article>
            </q-step>
          </q-stepper>
        </div>
      </template>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/core/user'
import { useOnboardingStore } from '../stores/onboardingStore'

type StepKey = 'llm' | 'agent' | 'tools' | 'connections' | 'skills' | 'processes'
type StepTone = 'blue' | 'violet' | 'amber' | 'teal'

interface SetupStep {
  name: number
  key: StepKey
  icon: string
  tone: StepTone
  route: string
  required: boolean
  complete: boolean | null
  canEdit: boolean
  tipKeys: string[]
}

interface StepStatus {
  label: string
  color: string
  textColor: string
  icon: string
}

const { t } = useI18n()
const authStore = useAuthStore()
const onboardingStore = useOnboardingStore()
const activeStep = ref(1)

const steps = computed<SetupStep[]>(() => [
  {
    name: 1,
    key: 'llm',
    icon: 'smart_toy',
    tone: 'blue',
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
    name: 2,
    key: 'agent',
    icon: 'support_agent',
    tone: 'violet',
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
    name: 3,
    key: 'connections',
    icon: 'hub',
    tone: 'teal',
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
    name: 4,
    key: 'tools',
    icon: 'construction',
    tone: 'amber',
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
    name: 5,
    key: 'skills',
    icon: 'psychology',
    tone: 'violet',
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
    name: 6,
    key: 'processes',
    icon: 'account_tree',
    tone: 'teal',
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

watch(
  () => steps.value.map(step => step.complete),
  () => {
    const firstIncompleteRequired = steps.value.find(step => step.required && step.complete !== true)
    const firstIncompleteOptional = steps.value.find(step => !step.required && step.complete !== true)
    activeStep.value = (firstIncompleteRequired ?? firstIncompleteOptional ?? steps.value[0])?.name ?? 1
  },
  { immediate: true },
)

function statusFor(step: SetupStep): StepStatus {
  if (step.complete === true) {
    return {
      label: t('onboarding.status.configured'),
      color: 'green-1',
      textColor: 'positive',
      icon: 'check_circle',
    }
  }
  if (!step.canEdit) {
    return {
      label: t('onboarding.status.restricted'),
      color: 'grey-3',
      textColor: 'grey-8',
      icon: 'lock',
    }
  }
  if (step.required) {
    return {
      label: t('onboarding.status.required'),
      color: 'red-1',
      textColor: 'negative',
      icon: 'priority_high',
    }
  }
  return {
    label: t('onboarding.status.recommended'),
    color: 'amber-1',
    textColor: 'orange-10',
    icon: 'lightbulb',
  }
}

function refresh(): void {
  void onboardingStore.fetchOverview()
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

.welcome-grid {
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.welcome-summary,
.welcome-stepper {
  border: 1px solid rgba(43, 60, 96, 0.09);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 12px 38px rgba(32, 46, 78, 0.07);
}

.welcome-summary {
  position: sticky;
  top: 16px;
  overflow: hidden;
  padding: 10px;
}

.welcome-summary__heading {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 14px 17px;
}

.welcome-summary__heading span {
  color: #263652;
  font-size: 0.9rem;
  font-weight: 800;
}

.welcome-summary__heading small {
  color: #8b95a9;
  font-size: 0.7rem;
  line-height: 1.45;
}

.summary-step {
  display: grid;
  width: 100%;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 11px;
  align-items: center;
  padding: 12px;
  color: inherit;
  border: 0;
  border-radius: 14px;
  outline: none;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 160ms ease, transform 160ms ease;
}

.summary-step:hover,
.summary-step--active {
  background: #f2f5fc;
}

.summary-step:focus-visible {
  outline: 2px solid #4f78dd;
  outline-offset: 2px;
}

.summary-step__icon {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 12px;
}

.summary-step__icon--blue { color: #3c6ed7; background: #edf3ff; }
.summary-step__icon--violet { color: #7651c5; background: #f3efff; }
.summary-step__icon--amber { color: #ad710d; background: #fff6dd; }
.summary-step__icon--teal { color: #087f70; background: #e8f8f4; }

.summary-step__copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.summary-step__copy strong {
  overflow: hidden;
  color: #33415d;
  font-size: 0.78rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.summary-step__copy small {
  color: #98a1b2;
  font-size: 0.65rem;
}

.summary-step__arrow {
  color: #aab1bf;
}

.welcome-stepper {
  overflow: hidden;
}

.welcome-stepper :deep(.q-stepper__header) {
  border-bottom: 1px solid #edf0f5;
  box-shadow: none;
}

.welcome-stepper :deep(.q-stepper__tab) {
  min-height: 82px;
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
  color: #7484a3;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.step-content h2 {
  margin: 0;
  color: #263652;
  font-size: clamp(1.35rem, 2.4vw, 1.8rem);
}

.step-lead {
  max-width: 720px;
  margin: 16px 0 20px;
  color: #66738c;
  font-size: 0.92rem;
  line-height: 1.65;
}

.step-tips {
  margin-bottom: 20px;
  padding: 18px 20px;
  border: 1px solid #e7ebf3;
  border-radius: 16px;
  background: #fafbfe;
}

.step-tips__title {
  display: flex;
  gap: 8px;
  align-items: center;
  color: #43577f;
  font-size: 0.76rem;
  font-weight: 800;
}

.step-tips ul {
  display: grid;
  gap: 8px;
  margin: 13px 0 0;
  padding-left: 20px;
  color: #68758c;
  font-size: 0.8rem;
  line-height: 1.55;
}

.permission-banner {
  margin-bottom: 18px;
  color: #6f5a2c;
  background: #fff8e7;
}

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

body.body--dark .welcome-state h1,
body.body--dark .welcome-summary__heading span,
body.body--dark .summary-step__copy strong,
body.body--dark .step-content h2 {
  color: #e1e7f2;
}

body.body--dark .welcome-summary,
body.body--dark .welcome-stepper {
  border-color: rgba(255, 255, 255, 0.09);
  background: rgba(29, 29, 29, 0.97);
  box-shadow: 0 12px 38px rgba(0, 0, 0, 0.3);
}

body.body--dark .summary-step:hover,
body.body--dark .summary-step--active {
  background: #252b38;
}

body.body--dark .welcome-stepper :deep(.q-stepper__header) {
  border-bottom-color: #343945;
}

body.body--dark .step-tips {
  border-color: #373d49;
  background: #232630;
}

body.body--dark .ready-banner {
  color: #9bdecd;
  border-color: #285f52;
  background: #18352f;
}

@media (max-width: 900px) {
  .welcome-grid {
    grid-template-columns: 1fr;
  }

  .welcome-summary {
    position: static;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .welcome-summary__heading {
    grid-column: 1 / -1;
  }

  .summary-step {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .summary-step__arrow {
    display: none;
  }
}

@media (max-width: 650px) {
  .welcome-page {
    padding: 10px;
  }

  .welcome-hero {
    grid-template-columns: 1fr;
    padding: 26px 22px;
    border-radius: 22px;
  }

  .welcome-hero__mark {
    display: none;
  }

  .welcome-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .summary-step {
    padding: 9px;
  }

  .welcome-stepper :deep(.q-stepper__header) {
    display: none;
  }

  .welcome-stepper :deep(.q-stepper__step-inner) {
    padding: 22px 16px;
  }

  .step-content__header {
    flex-direction: column;
  }

  .step-actions .q-btn {
    width: 100%;
  }
}
</style>
