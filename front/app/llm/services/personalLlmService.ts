import api from '@/core/api'

export interface PersonalLlmPreferences {
  profile_id: number | null
  voice_llm_id: number | null
  voice_mode: 'tts' | 'realtime'
  voice_code: string | null
}
export interface PersonalLlmOption { id: number; label: string }
export interface PersonalLlmOptions {
  profiles: PersonalLlmOption[]
  current_profile_id: number | null
  voices: PersonalLlmOption[]
  native_voices: { model_id: number; voice_code: string; label: string; caption: string }[]
  native_voices_error?: boolean
}

function preferencesUrl(userId?: number): string {
  return userId === undefined ? '/llm/me/preferences' : `/llm/users/${userId}/preferences`
}

export default {
  async preferences(userId?: number): Promise<PersonalLlmPreferences> {
    return (await api.get<PersonalLlmPreferences>(preferencesUrl(userId))).data
  },
  async options(): Promise<PersonalLlmOptions> {
    return (await api.get<PersonalLlmOptions>('/llm/me/options')).data
  },
  async save(values: PersonalLlmPreferences, userId?: number): Promise<void> {
    await api.put(preferencesUrl(userId), values)
  },
  async transcribe(audio: Blob, language: string, signal: AbortSignal): Promise<string> {
    const body = new FormData()
    body.append('file', audio, 'dictation')
    body.append('language', language)
    return (await api.post<{ text: string }>('/llm/me/transcription', body, { signal })).data.text
  },
  async speech(html: string, offset: number, signal: AbortSignal): Promise<{ audio: Blob; nextOffset: number; done: boolean }> {
    const response = await api.post<Blob>('/llm/me/speech', { html, offset }, { responseType: 'blob', signal })
    return { audio: response.data, nextOffset: Number(response.headers['x-next-offset']), done: response.headers['x-speech-done'] === 'true' }
  },
}
