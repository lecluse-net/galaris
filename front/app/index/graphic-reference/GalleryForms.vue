<template>
  <q-form class="form-grid" @submit="validated = true">
    <q-input v-model="text" outlined dense :label="t('graphicReference.name')" :hint="t('graphicReference.hint')" clearable />
    <q-input v-model="email" outlined dense type="email" :label="t('graphicReference.email')" />
    <q-input v-model="password" outlined dense type="password" :label="t('graphicReference.password')" />
    <q-input v-model.number="number" outlined dense type="number" :label="t('graphicReference.number')" />
    <q-input v-model="search" outlined dense :label="t('graphicReference.search')" clearable><template #prepend><q-icon name="search" /></template></q-input>
    <q-input v-model="area" outlined dense type="textarea" rows="2" :label="t('graphicReference.textarea')" />
    <q-select v-model="selected" :options="options" outlined dense clearable :label="t('graphicReference.select')" />
    <q-select v-model="multiple" :options="options" multiple use-chips outlined dense :label="t('graphicReference.multiple')" />
    <q-input v-model="date" type="date" stack-label outlined dense :label="t('graphicReference.date')" />
    <q-input v-model="time" type="time" stack-label outlined dense :label="t('graphicReference.time')" />
    <q-file v-model="file" outlined dense clearable :label="t('graphicReference.file')"><template #prepend><q-icon name="attach_file" /></template></q-file>
    <q-input :model-value="t('graphicReference.sample')" outlined dense readonly :label="t('graphicReference.readonly')" />
    <q-input :model-value="t('graphicReference.sample')" outlined dense disable :label="t('graphicReference.disabled')" />
    <q-input model-value="" outlined dense error :error-message="t('graphicReference.validation')" :label="t('graphicReference.invalid')" />
    <div><q-checkbox v-model="checked" :label="t('graphicReference.check')" /><q-checkbox :model-value="null" :label="t('graphicReference.neutral')" /></div>
    <div><q-toggle v-model="enabled" :label="t('graphicReference.toggle')" /><q-toggle :model-value="false" disable :label="t('graphicReference.disabled')" /></div>
    <q-option-group v-model="radio" :options="options" type="radio" />
    <div><label>{{ t('graphicReference.slider') }}<q-slider v-model="slider" :min="0" :max="100" label :aria-label="t('graphicReference.slider')" /></label></div>
    <div><label>{{ t('graphicReference.range') }}<q-range v-model="range" :min="0" :max="100" label :aria-label="t('graphicReference.range')" /></label></div>
    <div><label>{{ t('graphicReference.rating') }}<q-rating v-model="rating" :max="5" color="primary" size="24px" :aria-label="t('graphicReference.rating')" /></label></div>
    <q-field outlined dense :label="t('graphicReference.sample')" stack-label><template #control><div>{{ t('graphicReference.readonly') }}</div></template></q-field>
    <q-btn-toggle v-model="radio" :options="options" color="primary" :aria-label="t('graphicReference.radio')" />
    <div><q-radio v-model="radio" val="first" :label="t('graphicReference.first')" /><q-radio v-model="radio" val="second" :label="t('graphicReference.second')" /></div>
    <div><q-btn type="submit" color="primary" :label="t('graphicReference.save')" /><span v-if="validated" role="status" class="q-ml-sm">{{ t('graphicReference.saved') }}</span></div>
  </q-form>
  <div class="row q-col-gutter-md q-mt-xs">
    <div class="col-12 col-md-4"><q-date v-model="date" mask="YYYY-MM-DD" minimal /></div>
    <div class="col-12 col-md-4"><q-time v-model="time" format24h /></div>
    <div class="col-12 col-md-4"><q-color v-model="color" :aria-label="t('graphicReference.color')" /></div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { solaire } from '@/core/util'
const { t } = useI18n()
const text = ref(''), email = ref(''), password = ref(''), area = ref(''), search = ref('')
const number = ref(50), selected = ref(null), multiple = ref([]), file = ref<File | null>(null)
const date = ref('2026-10-18'), time = ref('14:30'), color = ref<string>(solaire.blue.accent)
const checked = ref(true), enabled = ref(true), radio = ref('first'), slider = ref(40), range = ref({ min: 20, max: 70 }), rating = ref(3)
const validated = ref(false)
const options = computed(() => ['first', 'second'].map(value => ({ label: t(`graphicReference.${value}`), value })))
</script>
<style scoped>
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 18px; }
label { display: grid; gap: 8px; }
.q-date, .q-time, .q-color { max-width: 100%; }
</style>
