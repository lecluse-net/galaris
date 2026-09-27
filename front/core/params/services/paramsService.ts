import api, { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { createSessionResponseCache, invalidateSessionReads } from '@/core/util/facade'
import type { AxiosResponse } from 'axios'

const parameters = createSessionResponseCache<ParamsListResponse>({
    group: 'parameters', sessionEvent: AUTH_TOKEN_CHANGED_EVENT, sessionKey: sessionGeneration, maxAgeMs: 300_000,
})

// Parameter response. Labels and descriptions are frontend translations keyed by
// parameter name and are no longer returned by the API.
export interface ParamItem {
    name: string
    value: string | null
    secret: boolean
    configured: boolean
    prompt: PromptParamMetadata | null
}

export interface PromptParamMetadata {
    default_value: string
    customized: boolean
    default_changed: boolean
}

export type PromptAction = 'keep_custom' | 'use_default'

// Parameter-list response.
export interface ParamsListResponse {
    params: ParamItem[]
}

// Parameter update payload.
export interface ParamUpdate {
    value: string | null
    clear_secret?: boolean
    prompt_action?: PromptAction
}

export interface ParamUpdateResponse extends ParamItem {
    status: string
}

// Parameter API.
export const paramsService = {
    /**
     * Return every parameter name and value.
     */
    getParamsList(force = false): Promise<AxiosResponse<ParamsListResponse>> {
        return parameters.read(signal => api.get('/params', { signal }), force)
    },

    /**
     * Update a parameter value.
     * @param name Parameter name.
     * @param update Payload containing the new value.
     */
    async updateParam(name: string, update: ParamUpdate): Promise<AxiosResponse<ParamUpdateResponse>> {
        const response = await api.put<ParamUpdateResponse>(`/params/${name}`, update)
        invalidateSessionReads('parameters')
        return response
    }
}
