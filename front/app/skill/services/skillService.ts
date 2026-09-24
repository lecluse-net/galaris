import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export interface Skill {
    id: number
    code: string
    label: string
    system: boolean
    available: boolean
    valid: boolean
    validation_error: string | null
    description: string | null
    category_id: number | null
    category_label: string | null
    file_count: number
    total_size: number
    created_at: string
    updated_at: string | null
}

export interface SkillCreate {
    code: string
    label: string
    markdown?: string | null
    category_id?: number | null
}

export interface SkillUpdate {
    label?: string
    markdown?: string
}

export interface SkillFile {
    path: string
    name: string
    size: number
    text: boolean
}

export interface SkillFileContent {
    path: string
    content: string
    size: number
}

export interface SkillAgent {
    id: number
    code: string
    label: string
    driver: string
}

export interface SkillRescanResult {
    created: number
    restored: number
    invalid_directories: string[]
}

export interface SkillImportResult {
    skill: Skill
    created: boolean
}

export type SkillAuthorizationState = 'default' | 'enabled' | 'disabled'
export type SkillGlobalAuthorizationState = 'enabled' | 'disabled'
export type SkillCategoryAuthorizationState = SkillAuthorizationState

export interface SkillCategory {
    id: number
    label: string
    skill_count: number
}

export interface SkillAuthorization {
    skill_id: number
    code: string
    label: string
    agent_id: number
    agent_code: string
    agent_label: string
    agent_driver: string
    description: string | null
    category_id: number | null
    category_label: string | null
    available: boolean
    valid: boolean
    global_state: SkillGlobalAuthorizationState
    category_state: SkillCategoryAuthorizationState
    agent_state: SkillAuthorizationState
    effective: boolean
}

export interface SkillAuthorizationsResponse {
    authorizations: SkillAuthorization[]
}

export interface SkillAuthorizationResult extends SkillAuthorization {
    affected_agent_ids: number[]
}

export interface SkillCategoryResult {
    category: SkillCategory
    affected_agent_ids: number[]
}

export interface SkillCategoryAuthorizationResult {
    category_id: number
    agent_id: number
    state: SkillCategoryAuthorizationState
    affected_agent_ids: number[]
}

export interface SkillCategoryDeleteResult {
    affected_skill_ids: number[]
    affected_agent_ids: number[]
}

export interface SkillCategoryAssignmentResult {
    skill: Skill
    affected_agent_ids: number[]
}

export interface SkillDeleteResult {
    affected_agent_ids: number[]
}

export type LearnedSkillOperation = 'CREATE' | 'REINFORCE' | 'REVISE' | 'WEAKEN'

export interface LearnedSkillEvidence {
    id: string
    source_ref: string
    operation: LearnedSkillOperation
    polarity: 'positive' | 'negative'
    weight: number
    confidence: number
    evidence_refs: string[]
    rationale: string
    created_at: string
}

export interface LearnedSkill {
    id: string
    agent_id: number
    code: string
    label: string
    description: string
    revision: number
    positive_weight: number
    negative_weight: number
    evidence_count: number
    score: number
    suspended: boolean
    injectable: boolean
    last_evidence_at: string | null
    created_at: string
    updated_at: string | null
}

export interface LearnedSkillDetail extends LearnedSkill {
    markdown: string
    evidences: LearnedSkillEvidence[]
}

export interface LearnedSkillPage {
    items: LearnedSkill[]
    total: number
    page: number
    page_size: number
}

export interface LearnedSkillMutationResult {
    skill: LearnedSkill
    affected_agent_ids: number[]
}

export interface LearnedSkillLearningStatus {
    mode: 'off' | 'observe' | 'learn'
    enabled: boolean
}

export const skillService = {
    getSkills(): Promise<AxiosResponse<Skill[]>> {
        return api.get('/skills')
    },
    getSkill(id: number): Promise<AxiosResponse<Skill>> {
        return api.get(`/skills/${id}`)
    },
    createSkill(data: SkillCreate): Promise<AxiosResponse<Skill>> {
        return api.post('/skills', data)
    },
    updateSkill(id: number, data: SkillUpdate): Promise<AxiosResponse<Skill>> {
        return api.put(`/skills/${id}`, data)
    },
    deleteSkill(id: number): Promise<AxiosResponse<SkillDeleteResult>> {
        return api.delete(`/skills/${id}`)
    },
    importSkill(
        file: File,
        options: { code?: string; label?: string; overwrite?: boolean },
    ): Promise<AxiosResponse<SkillImportResult>> {
        const form = new FormData()
        form.append('file', file)
        if (options.code?.trim()) form.append('code', options.code.trim())
        if (options.label?.trim()) form.append('label', options.label.trim())
        form.append('overwrite', String(Boolean(options.overwrite)))
        return api.post('/skills/import', form)
    },
    rescan(): Promise<AxiosResponse<SkillRescanResult>> {
        return api.post('/skills/rescan')
    },
    getLearnedSkills(params: {
        agentId?: number | null
        page?: number
        pageSize?: number
    } = {}): Promise<AxiosResponse<LearnedSkillPage>> {
        return api.get('/skills/learned', {
            params: {
                agent_id: params.agentId ?? undefined,
                page: params.page ?? 1,
                page_size: params.pageSize ?? 50,
            },
        })
    },
    getLearnedSkillStatus(): Promise<AxiosResponse<LearnedSkillLearningStatus>> {
        return api.get('/skills/learned/status')
    },
    getLearnedSkill(id: string): Promise<AxiosResponse<LearnedSkillDetail>> {
        return api.get(`/skills/learned/${id}`)
    },
    setLearnedSkillSuspended(
        id: string,
        suspended: boolean,
    ): Promise<AxiosResponse<LearnedSkillMutationResult>> {
        return api.put(`/skills/learned/${id}/suspension`, { suspended })
    },
    getFiles(id: number): Promise<AxiosResponse<SkillFile[]>> {
        return api.get(`/skills/${id}/files`)
    },
    getFileContent(id: number, path: string): Promise<AxiosResponse<SkillFileContent>> {
        return api.get(`/skills/${id}/content`, { params: { path } })
    },
    downloadSkill(id: number): Promise<AxiosResponse<Blob>> {
        return api.get(`/skills/${id}/download`, { responseType: 'blob' })
    },
    downloadFile(id: number, path: string): Promise<AxiosResponse<Blob>> {
        return api.get(`/skills/${id}/file`, { params: { path }, responseType: 'blob' })
    },
    getAgents(): Promise<AxiosResponse<SkillAgent[]>> {
        return api.get('/skills/agents')
    },
    getCategories(): Promise<AxiosResponse<SkillCategory[]>> {
        return api.get('/skills/categories')
    },
    createCategory(label: string): Promise<AxiosResponse<SkillCategoryResult>> {
        return api.post('/skills/categories', { label })
    },
    updateCategory(id: number, label: string): Promise<AxiosResponse<SkillCategoryResult>> {
        return api.put(`/skills/categories/${id}`, { label })
    },
    deleteCategory(id: number): Promise<AxiosResponse<SkillCategoryDeleteResult>> {
        return api.delete(`/skills/categories/${id}`)
    },
    assignCategory(
        skillId: number,
        categoryId: number | null,
    ): Promise<AxiosResponse<SkillCategoryAssignmentResult>> {
        return api.put(`/skills/${skillId}/category`, { category_id: categoryId })
    },
    getAuthorizations(
        agentId?: number | null,
        skillId?: number | null,
        categoryId?: number | null,
    ): Promise<AxiosResponse<SkillAuthorizationsResponse>> {
        const params: Record<string, number> = {}
        if (agentId != null) params.agent_id = agentId
        if (skillId != null) params.skill_id = skillId
        if (categoryId != null) params.category_id = categoryId
        return api.get('/skills/authorizations', { params })
    },
    setCategoryAuthorization(
        categoryId: number,
        agentId: number,
        state: SkillCategoryAuthorizationState,
    ): Promise<AxiosResponse<SkillCategoryAuthorizationResult>> {
        return api.put(
            `/skills/categories/${categoryId}/authorization/agents/${agentId}`,
            { state },
        )
    },
    setGlobalAuthorization(
        skillId: number,
        agentId: number,
        state: SkillGlobalAuthorizationState,
    ): Promise<AxiosResponse<SkillAuthorizationResult>> {
        return api.put(
            `/skills/${skillId}/authorization/global`,
            { state },
            { params: { agent_id: agentId } },
        )
    },
    setAgentAuthorization(
        skillId: number,
        agentId: number,
        state: SkillAuthorizationState,
    ): Promise<AxiosResponse<SkillAuthorizationResult>> {
        return api.put(`/skills/${skillId}/authorization/agents/${agentId}`, { state })
    },
}
