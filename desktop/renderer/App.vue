<template>
  <main class="desktop-launcher q-pa-lg">
    <q-card flat bordered class="launcher-card">
      <q-card-section class="row items-center q-gutter-md">
        <img :src="icon" alt="" width="56" height="56">
        <div><h1 class="text-h5 q-my-none">{{ t('title') }}</h1><p class="q-mb-none text-body2">{{ t('intro') }}</p></div>
      </q-card-section>
      <q-separator />
      <q-card-section>
        <q-form @submit="connect">
          <q-input v-model="server" outlined autofocus type="url" :label="t('server')" :hint="t('hint')" :disable="state.connecting" autocomplete="url" />
          <q-banner v-if="state.error" rounded class="error-banner q-mt-lg" role="alert">
            <template #avatar><q-icon name="error_outline" color="negative" /></template>{{ t(state.error) }}
          </q-banner>
          <div class="row q-gutter-sm q-mt-lg">
            <q-btn type="submit" color="primary" :label="t('connect')" :loading="state.connecting" :disable="!server.trim()" />
            <q-btn v-if="state.connecting" outline color="primary" :label="t('cancel')" @click="windowAPI.cancel()" />
          </div>
        </q-form>
      </q-card-section>
      <q-separator />
      <q-card-section aria-live="polite">
        <h2 class="text-subtitle1 q-mt-none q-mb-sm">{{ t('updates') }}</h2>
        <p class="text-body2">{{ t(state.update.status, { version: state.update.version, percent: Math.floor(state.update.percent) }) }}</p>
        <p v-if="state.diagnosticsFailed" role="alert">{{ t('diagnosticsFailed') }}</p>
        <q-linear-progress v-if="state.update.status === 'downloading'" :value="state.update.percent / 100" class="q-mb-md" />
        <q-btn v-if="state.update.status === 'ready'" color="primary" :label="t('restart')" @click="windowAPI.installUpdate()" />
        <q-btn v-else-if="!['disabled', 'manual'].includes(state.update.status)" outline color="primary" :label="t('check')" :loading="['checking', 'downloading'].includes(state.update.status)" @click="windowAPI.checkUpdates()" />
        <p class="text-caption q-mt-md q-mb-none">{{ t('version', { version: state.version }) }}</p>
      </q-card-section>
    </q-card>
  </main>
</template>

<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DesktopState } from '../src/contracts'
import icon from '../../front/public/pwa/icon-512.png'

const { initialState } = defineProps<{ initialState: DesktopState }>()
const { t } = useI18n()
const windowAPI = window.galarisDesktop
const state = ref(initialState)
const server = ref(initialState.server)
onUnmounted(windowAPI.onState(value => { state.value = value }))
async function connect(): Promise<void> { await windowAPI.connect(server.value) }
</script>

<style>
body { margin: 0; background: #FFFFFF; color: #292C30; }
body.body--dark { background: #101010; color: #EEEEF0; }
.desktop-launcher { min-height: 100vh; display: grid; place-items: center; }
.launcher-card { width: 100%; max-width: 560px; }
.error-banner { background: var(--solaire-red-light); }
.body--dark .error-banner { background: var(--solaire-red-dark); }
</style>
