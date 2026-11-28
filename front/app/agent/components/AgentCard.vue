<template>
  <q-card class="agent-card" :class="{ 'agent-card--compact': compact }" flat :bordered="!compact">
    <q-card-section horizontal class="agent-card-horizontal">
      <!-- Avatar Section (Left) -->
      <q-card-section class="bg-grey-2 agent-avatar-section">
        <div v-if="agent.has_avatar && avatarUrl" class="agent-image-container">
          <img
            :src="avatarUrl"
            :alt="`${agent.first_name} ${agent.last_name}`"
            class="agent-image"
          />
        </div>
        <div v-else class="flex flex-center full-height">
          <q-avatar size="112px" class="agent-fallback-avatar">
            {{ initials }}
          </q-avatar>
        </div>
      </q-card-section>

      <!-- Info Section (Right) -->
      <q-card-section class="agent-info-section q-pa-sm">
        <div class="agent-identity-section">
          <div class="agent-name-row row items-start no-wrap">
            <div class="agent-name col text-h6 text-weight-bold">
              {{ agent.first_name }} {{ agent.last_name }}
            </div>
            <div v-if="profileLabel" class="profile-name text-caption text-grey-7 text-right">
              {{ profileLabel }}
            </div>
          </div>
          <div class="agent-meta-row row items-baseline no-wrap">
            <div
              class="agent-job-title col ellipsis"
              :class="agent.job_title
                ? 'text-body1 text-weight-medium text-dark'
                : 'text-body2 text-grey-6'"
            >
              {{ agent.job_title || $t('agent.noJobTitle') }}
            </div>
            <div
              v-if="agent.user"
              class="agent-manager text-caption text-grey-7 ellipsis"
              :title="agent.user.display_name || agent.user.email"
            >
              {{ $t('agent.managerLabelShort') }} · {{ agent.user.display_name || agent.user.email }}
            </div>
          </div>

          <q-separator class="q-mt-xs" />
        </div>

        <!-- Personality Summary -->
        <div
          class="agent-summary clickable-text-zone"
          @click="emit('open-summary', 'personality')"
        >
          <div class="text-caption text-weight-medium text-primary q-mb-xs">
            <q-icon name="psychology" size="xs" class="q-mr-xs" />
            {{ $t('agent.personality') }}
          </div>
          <div
            v-if="agent.personality"
            class="text-body2 text-grey-8 ellipsis-2-lines"
            style="min-height: 2.5em;"
          >
            {{ truncateText(richTextExcerpt(agent.personality ?? ''), 140) }}
          </div>
          <div v-else class="text-body2 text-grey-5" style="min-height: 2.5em;">
            {{ $t('agent.notDefinedF') }}
          </div>
        </div>

        <!-- Job Description Summary -->
        <div
          class="agent-summary clickable-text-zone"
          @click="emit('open-summary', 'job_description')"
        >
          <div class="text-caption text-weight-medium text-primary q-mb-xs">
            <q-icon name="work" size="xs" class="q-mr-xs" />
            {{ $t('agent.jobDescription') }}
          </div>
          <div
            v-if="agent.job_description"
            class="text-body2 text-grey-8 ellipsis-2-lines"
            style="min-height: 2.5em;"
          >
            {{ truncateText(richTextExcerpt(agent.job_description ?? ''), 140) }}
          </div>
          <div v-else class="text-body2 text-grey-5" style="min-height: 2.5em;">
            {{ $t('agent.notDefinedF') }}
          </div>
        </div>
      </q-card-section>
    </q-card-section>
    <q-separator />
    <slot />
  </q-card>
</template>

<script setup lang="ts">
import { richTextExcerpt } from '@/core/util'
import type { Agent } from '../contracts'

defineProps<{
  agent: Agent
  avatarUrl?: string
  initials: string
  profileLabel: string
  compact?: boolean
}>()
const emit = defineEmits<{ 'open-summary': [field: 'personality' | 'job_description'] }>()

const truncateText = (text: string | null, maxLength: number) => {
  if (!text) return ''
  return text.length > maxLength ? text.substring(0, maxLength) + '...' : text
}
</script>

<style scoped>
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Clickable text zones for personality and job description */
.clickable-text-zone {
  cursor: pointer;
  border-radius: 4px;
  padding: 4px;
  margin: -4px;
  transition: background-color 0.2s ease;
}

.clickable-text-zone:hover {
  background-color: rgba(0, 0, 0, 0.05);
}

/* Agent Card Styles */
.agent-card {
  transition: box-shadow 0.3s ease;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.agent-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.agent-card--compact { border: 0; border-radius: 0; box-shadow: none; }

.agent-card-horizontal {
  display: grid;
  flex: 1 0 auto;
  grid-template-columns: minmax(140px, 180px) minmax(0, 1fr);
  min-height: 207px;
}

.agent-avatar-section {
  padding: 0;
  overflow: hidden;
  position: relative;
  height: 100%;
  min-width: 0;
}

.agent-info-section {
  min-width: 0;
}

.agent-identity-section {
  min-width: 0;
}

.agent-summary {
  margin-bottom: 8px;
}

.agent-image-container {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.agent-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
}

body.body--dark .agent-fallback-avatar {
  color: #9ab2f0;
  background: linear-gradient(145deg, #24304d, #1e2740);
}

.agent-fallback-avatar {
  color: #3f69d8;
  background: linear-gradient(145deg, #e7edff, #f3f6ff);
  box-shadow: 0 8px 22px rgba(63, 105, 216, 0.16);
  font-size: clamp(72px, 28vw, 112px) !important;
  font-weight: 750;
  letter-spacing: 0.04em;
}

.ellipsis-2-lines {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.profile-name {
  min-width: 0;
  max-width: 50%;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.agent-name-row {
  gap: 8px;
}

.agent-name {
  line-height: 1.15;
  overflow-wrap: anywhere;
}

.agent-manager {
  max-width: 42%;
  margin-left: 8px;
  line-height: 1.2;
  text-align: right;
}

@media (max-width: 1023.98px) {
  .agent-card-horizontal {
    grid-template-columns: 84px minmax(0, 1fr);
    min-height: 0;
  }

  .agent-avatar-section {
    grid-column: 1;
    grid-row: 1;
    width: 84px;
    height: auto;
    min-height: 0;
    aspect-ratio: 1;
  }

  .agent-avatar-section > .flex {
    position: absolute;
    inset: 0;
  }

  .agent-avatar-section .agent-fallback-avatar {
    width: 54px !important;
    height: 54px !important;
  }

  .agent-info-section {
    display: contents;
  }

  .agent-identity-section {
    grid-column: 2;
    grid-row: 1;
    padding: 8px;
  }

  .agent-name {
    font-size: 1rem;
    line-height: 1.2;
  }

  .agent-job-title {
    font-size: 0.875rem;
    line-height: 1.25;
  }

  .agent-meta-row {
    display: block;
  }

  .agent-job-title,
  .agent-manager {
    width: 100%;
    max-width: 100%;
  }

  .agent-manager {
    margin-top: 2px;
    margin-left: 0;
    text-align: right;
  }

  .agent-summary {
    grid-column: 1 / -1;
    margin: 0;
    padding: 4px 12px;
  }

  .agent-summary + .agent-summary {
    padding-top: 0;
  }

  .agent-summary .text-body2 {
    min-height: 0 !important;
  }
}
</style>
