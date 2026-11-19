<template>
  <div>
    <template v-if="!hideIdentity">
      <div class="text-subtitle1 text-weight-medium">{{ label(preview.manifest.label) }}</div>
      <div class="text-caption text-break">{{ preview.manifest.code }} · {{ preview.manifest.version }}</div>
      <p class="q-mt-sm text-break">{{ label(preview.manifest.description) }}</p>
    </template>

    <div class="text-subtitle2 q-mb-xs">{{ t('plugins.capabilities') }}</div>
    <ul class="q-my-none q-pl-lg text-break">
      <li v-for="capability in preview.manifest.contributions" :key="capability.code">
        <span>{{ label(capability.label) }}</span>
        <span class="text-caption"> · {{ t(`plugins.families.${capability.family}`) }} · {{ capability.code }}</span>
        <div v-if="downloadTemplates && capability.family === 'data_template'" class="q-mt-xs">
          <q-btn outline color="primary" :disable="busy" :label="t('plugins.downloadTemplate')" @click="emit('download', capability.code)" />
        </div>
      </li>
    </ul>

    <dl v-if="'compatibility' in preview" class="q-mt-md q-mb-none">
      <dt class="text-weight-medium">{{ t('plugins.compatibility') }}</dt>
      <dd class="q-ml-none">{{ t(`plugins.messages.${preview.compatibility}`) }}</dd>
      <dd class="q-ml-none text-caption">{{ t('plugins.hostRange', {
        host: preview.host_version,
        min: preview.manifest.minimum_galaris_version,
        max: preview.manifest.maximum_galaris_version_exclusive,
      }) }}</dd>
      <dt class="text-weight-medium q-mt-sm">{{ t('plugins.signer') }}</dt>
      <dd class="q-ml-none text-caption text-break">{{ preview.signer }}</dd>
      <template v-if="preview.manifest.python_requirements?.length">
        <dt class="text-weight-medium q-mt-sm">{{ t('plugins.dependencies') }}</dt>
        <dd v-for="requirement in preview.manifest.python_requirements" :key="requirement" class="q-ml-none text-caption">{{ requirement }}</dd>
      </template>
      <template v-if="preview.manifest.runtime_requirements?.length">
        <dt class="text-weight-medium q-mt-sm">{{ t('plugins.runtimeDependencies') }}</dt>
        <dd v-for="requirement in preview.manifest.runtime_requirements" :key="requirement.code" class="q-ml-none text-caption text-break">
          {{ requirement.code }} · {{ requirement.image }}
        </dd>
      </template>
    </dl>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { LocalizedPluginText, PluginPreview, SampleRelease } from '../services/pluginApi'

defineProps<{ preview: PluginPreview | SampleRelease; hideIdentity?: boolean; downloadTemplates?: boolean; busy?: boolean }>()
const emit = defineEmits<{ download: [code: string] }>()
const { t, locale } = useI18n()
function label(text: LocalizedPluginText): string {
  return locale.value.startsWith('fr') ? text.fr : text.en
}
</script>

<style scoped>
.text-break { overflow-wrap: anywhere; }
</style>
