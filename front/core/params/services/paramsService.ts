import api from '@/core/api'
import type { AxiosResponse } from 'axios'

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
    getParamsList(): Promise<AxiosResponse<ParamsListResponse>> {
        return api.get('/params')
    },

    /**
     * Update a parameter value.
     * @param name Parameter name.
     * @param update Payload containing the new value.
     */
    updateParam(name: string, update: ParamUpdate): Promise<AxiosResponse<ParamUpdateResponse>> {
        return api.put(`/params/${name}`, update)
    }
}
