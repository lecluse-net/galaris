import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as vue from 'vue'
import ts from 'typescript'
import { solaireCss } from '../../../core/util/solaire.ts'

const source = readFileSync(new URL('./LlmUsageManager.vue', import.meta.url), 'utf8')

function setupUsageManager(t) {
  const { descriptor } = parse(source)
  const code = ts.transpileModule(compileScript(descriptor, { id: 'usage-label-test' }).content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const llmStore = vue.reactive({ llms: [
    { id: 22, label: 'Whisper', provider_name: 'OpenAI', primary_capability: 'transcription', service_capabilities: ['transcription'], input_audio: true, output_text: true },
    { id: 37, label: 'Z.ai: GLM Flash Latest', provider_name: 'OpenRouter', primary_capability: 'vision', service_capabilities: ['vision', 'chat'], input_video: true, output_text: true },
  ] })
  const profile = vue.reactive({ id: 2, audio_llm_id: 22, video_llm_id: 37, transcription_llm_id: 22 })
  const modules = {
    vue: { ...vue, onMounted() {} },
    quasar: { useQuasar: () => ({ notify() {} }) },
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    '../stores/llmProviderStore': { useLLMProviderStore: () => llmStore },
    '../stores/llmProfileStore': { useLLMProfileStore: () => ({ getProfileById: () => profile }) },
    '@/core/authorize': { privileges: {}, usePrivilegeStore: () => ({ hasPrivilege: () => true }) },
    '@/core/util': { solaireCss },
  }
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => {
    assert.ok(name in modules, `Unexpected dependency ${name}`)
    return modules[name]
  }, module, module.exports)
  const scope = vue.effectScope()
  t.after(() => scope.stop())
  const state = scope.run(() => module.exports.default.setup({}, { expose() {} }))
  state.selectedProfileId.value = profile.id
  return { state, profile, llmStore }
}

test('saved multimedia models retain their names when capability filters exclude them', t => {
  const { state, llmStore } = setupUsageManager(t)
  // Simulate a catalogue refresh that makes saved models ineligible.
  for (const model of llmStore.llms) model.output_text = false
  assert.deepEqual(state.optionsForRow('audio_llm_id'), [])
  assert.deepEqual(state.optionsForRow('video_llm_id'), [])
  assert.equal(state.selectedModelLabel('audio_llm_id'), 'Whisper (OpenAI)')
  assert.equal(state.selectedModelLabel('video_llm_id'), 'Z.ai: GLM Flash Latest (OpenRouter)')
  assert.equal(state.selectedModelLabel('transcription_llm_id'), 'Whisper (OpenAI)')
})

for (const primary of ['vision', 'chat']) {
  test(`a multimodal model with ${primary} as primary remains available for every supported usage`, t => {
    const { state, llmStore } = setupUsageManager(t)
    llmStore.llms = [
      { id: 37, label: 'Multimodal', provider_name: 'Provider', primary_capability: primary,
        service_capabilities: ['vision', 'chat'], input_text: true, input_image: true,
        input_audio: true, input_video: true, output_text: true },
      { id: 38, label: 'Speech only', provider_name: 'Provider', primary_capability: 'speech',
        service_capabilities: ['speech'], input_text: true, output_audio: true },
    ]
    for (const field of ['text_ultra_low', 'text_low', 'text_standard', 'text_high', 'vision', 'audio', 'video']) {
      assert.deepEqual(state.optionsForRow(`${field}_llm_id`).map(option => option.value), [37], field)
    }
  })
}

test('cleared and unavailable models never display a raw database identifier', t => {
  const { state, profile } = setupUsageManager(t)
  profile.audio_llm_id = null
  assert.equal(state.selectedModelLabel('audio_llm_id'), undefined)
  profile.video_llm_id = 999
  assert.equal(state.selectedModelLabel('video_llm_id'), 'llm.unavailable')
})

test('selected model labels follow catalogue refreshes and profile changes', t => {
  const { state, profile, llmStore } = setupUsageManager(t)
  llmStore.llms[0].label = 'Whisper local'
  assert.equal(state.selectedModelLabel('audio_llm_id'), 'Whisper local (OpenAI)')
  profile.audio_llm_id = 37
  assert.equal(state.selectedModelLabel('audio_llm_id'), 'Z.ai: GLM Flash Latest (OpenRouter)')
  llmStore.llms = []
  assert.equal(state.selectedModelLabel('audio_llm_id'), 'llm.unavailable')
})

test('every LLM usage is assigned once to the appropriate category', t => {
  const { state } = setupUsageManager(t)
  const groups = state.modelGroups.value
  const rows = groups.flatMap(group => group.rows)
  assert.equal(rows.length, 14)
  assert.equal(new Set(rows.map(row => row.modelField)).size, rows.length)
  assert.deepEqual(
    new Set(groups.map(group => group.key)),
    new Set(['text', 'image', 'audio', 'multimedia', 'embedding']),
  )
  const categories = Object.fromEntries(groups.flatMap(group => group.rows.map(row => [row.modelField, group.key])))
  assert.equal(categories.transcription_llm_id, 'audio')
  for (const column of ['audio_llm_id', 'video_llm_id', 'sound_generation_llm_id', 'music_generation_llm_id', 'video_generation_llm_id']) {
    assert.equal(categories[column], 'multimedia')
  }
})

test('profile reasoning maps automatic and explicit efforts to the canonical scale', t => {
  const { state } = setupUsageManager(t)
  assert.deepEqual(
    [null, 'none', 'low', 'medium', 'high', 'xhigh', 'max'].map(state.reasoningLevel),
    [-1, 0, 1, 2, 3, 4, 5],
  )
})
