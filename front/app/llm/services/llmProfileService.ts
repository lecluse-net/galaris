import api from '@/core/api'
import type { ReasoningEffort } from '../types'

export type { ReasoningEffort } from '../types'

// =============================================================================
// LLM configuration profiles (column-based model).
// =============================================================================

// A profile holds four shared text tiers plus specialized model usages.
export interface LlmProfile {
    id: number
    code: string
    label: string
    created_at: string
    updated_at: string | null
    text_ultra_low_llm_id: number | null
    text_low_llm_id: number | null
    text_standard_llm_id: number | null
    text_high_llm_id: number | null
    text_ultra_low_reasoning_effort: ReasoningEffort | null
    text_low_reasoning_effort: ReasoningEffort | null
    text_standard_reasoning_effort: ReasoningEffort | null
    text_high_reasoning_effort: ReasoningEffort | null
    vision_llm_id: number | null
    document_llm_id: number | null
    audio_llm_id: number | null
    video_llm_id: number | null
    sound_generation_llm_id: number | null
    music_generation_llm_id: number | null
    video_generation_llm_id: number | null
    image_llm_id: number | null
    transcription_llm_id: number | null
    vector_llm_id: number | null
    decision_llm_id: number | null
    decision_fallback_policy: 'text_on_failure' | 'disabled'
}

export interface LlmProfileListResponse {
    profiles: LlmProfile[]
    current_profile_id: number | null
}

export interface LlmProfileCreate {
    label: string
}

export interface LlmProfileUpdate {
    label?: string
    // A null column clears this usage. Absent keys are left untouched.
    text_ultra_low_llm_id?: number | null
    text_low_llm_id?: number | null
    text_standard_llm_id?: number | null
    text_high_llm_id?: number | null
    text_ultra_low_reasoning_effort?: ReasoningEffort | null
    text_low_reasoning_effort?: ReasoningEffort | null
    text_standard_reasoning_effort?: ReasoningEffort | null
    text_high_reasoning_effort?: ReasoningEffort | null
    vision_llm_id?: number | null
    document_llm_id?: number | null
    audio_llm_id?: number | null
    video_llm_id?: number | null
    sound_generation_llm_id?: number | null
    music_generation_llm_id?: number | null
    video_generation_llm_id?: number | null
    image_llm_id?: number | null
    transcription_llm_id?: number | null
    vector_llm_id?: number | null
    decision_llm_id?: number | null
    decision_fallback_policy?: 'text_on_failure' | 'disabled'
}

export interface LlmProfileUseResponse {
    profile_id: number
    current_profile_id: number
}

export default {
    getProfiles() {
        return api.get<LlmProfileListResponse>('/llm-profiles')
    },

    getProfile(id: number) {
        return api.get<LlmProfile>(`/llm-profiles/${id}`)
    },

    createProfile(data: LlmProfileCreate) {
        return api.post<LlmProfile>('/llm-profiles', data)
    },

    updateProfile(id: number, data: LlmProfileUpdate) {
        return api.put<LlmProfile>(`/llm-profiles/${id}`, data)
    },

    deleteProfile(id: number) {
        return api.delete(`/llm-profiles/${id}`)
    },

    useProfile(id: number) {
        return api.post<LlmProfileUseResponse>(`/llm-profiles/${id}/use`)
    },
}
