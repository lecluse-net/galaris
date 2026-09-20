import api from '@/core/api'
import type { AxiosResponse } from 'axios'
import type { TokenResponse, User } from '@/core/user/services/authService'


// ==================== Types ====================

export interface PaginatedResponse<T> {
    items: T[]
    total: number
}

export interface Privilege {
    id: number
    code: string
    display_name: string | null
    privilege_list_id: number | null
}

export interface PrivilegeCreate {
    code: string
}

export interface Role {
    id: number
    code: string
    display_name: string | null
}

export interface RoleCreate {
    code: string
    display_name?: string
}

export interface RoleUpdate {
    code?: string
    display_name?: string
}

export interface RoleWithPrivileges extends Role {
    privileges: Privilege[]
}

export interface Assignment {
    id: number
    user_id: number
    role_id: number
    is_default: boolean
}

export interface AssignmentWithRole extends Assignment {
    role: Role
    user: User
}

export interface AssignmentCreate {
    user_id: number
    role_id: number
}

export interface RolePrivilegeAction {
    privilege_ids: number[]
}

// ==================== Privilege Lists ====================

export interface PrivilegeList {
    id: number
    display_name: string
    privileges: Privilege[]
}

export interface PrivilegeListCreate {
    display_name: string
}

export interface PrivilegeListUpdate {
    display_name: string
}

export interface PrivilegeListAction {
    privilege_ids: number[]
}

// ==================== Service ====================

export const authorizeService = {
    // ---------- Privileges ----------
    async listPrivileges(): Promise<Privilege[]> {
        const response: AxiosResponse<Privilege[]> = await api.get('/authorize/privileges')
        return response.data
    },

    // ---------- Privilege Lists ----------
    async listPrivilegeLists(): Promise<PrivilegeList[]> {
        const response: AxiosResponse<PrivilegeList[]> = await api.get('/authorize/privilege-lists')
        return response.data
    },

    async createPrivilegeList(list: PrivilegeListCreate): Promise<PrivilegeList> {
        const response: AxiosResponse<PrivilegeList> = await api.post('/authorize/privilege-lists', list)
        return response.data
    },

    async updatePrivilegeList(id: number, list: PrivilegeListUpdate): Promise<PrivilegeList> {
        const response: AxiosResponse<PrivilegeList> = await api.put(`/authorize/privilege-lists/${id}`, list)
        return response.data
    },

    async deletePrivilegeList(id: number): Promise<void> {
        await api.delete(`/authorize/privilege-lists/${id}`)
    },

    async addPrivilegesToList(listId: number, privilegeIds: number[]): Promise<PrivilegeList> {
        const response: AxiosResponse<PrivilegeList> = await api.post(`/authorize/privilege-lists/${listId}/privileges`, {
            privilege_ids: privilegeIds
        })
        return response.data
    },

    async removePrivilegesFromList(listId: number, privilegeIds: number[]): Promise<PrivilegeList> {
        const response: AxiosResponse<PrivilegeList> = await api.delete(`/authorize/privilege-lists/${listId}/privileges`, {
            data: { privilege_ids: privilegeIds }
        })
        return response.data
    },

    // ---------- Roles ----------
    async listRoles(): Promise<RoleWithPrivileges[]> {
        const response: AxiosResponse<RoleWithPrivileges[]> = await api.get('/authorize/roles')
        return response.data
    },

    async getRole(id: number): Promise<RoleWithPrivileges> {
        const response: AxiosResponse<RoleWithPrivileges> = await api.get(`/authorize/roles/${id}`)
        return response.data
    },

    async createRole(role: RoleCreate): Promise<Role> {
        const response: AxiosResponse<Role> = await api.post('/authorize/roles', role)
        return response.data
    },

    async updateRole(id: number, role: RoleUpdate): Promise<Role> {
        const response: AxiosResponse<Role> = await api.put(`/authorize/roles/${id}`, role)
        return response.data
    },

    async deleteRole(id: number): Promise<void> {
        await api.delete(`/authorize/roles/${id}`)
    },

    async addPrivilegesToRole(roleId: number, privilegeIds: number[]): Promise<RoleWithPrivileges> {
        const response: AxiosResponse<RoleWithPrivileges> = await api.post(`/authorize/roles/${roleId}/privileges`, {
            privilege_ids: privilegeIds
        })
        return response.data
    },

    async removePrivilegesFromRole(roleId: number, privilegeIds: number[]): Promise<RoleWithPrivileges> {
        const response: AxiosResponse<RoleWithPrivileges> = await api.delete(`/authorize/roles/${roleId}/privileges`, {
            data: { privilege_ids: privilegeIds }
        })
        return response.data
    },

    // ---------- Assignments ----------
    async listAssignments(page: number = 1, limit: number = 10): Promise<PaginatedResponse<AssignmentWithRole>> {
        const offset = (page - 1) * limit
        const response: AxiosResponse<PaginatedResponse<AssignmentWithRole>> = await api.get('/authorize/assignments', {
            params: {
                skip: offset,
                limit: limit
            }
        })
        return response.data
    },

    async getUserAssignments(userId: number): Promise<AssignmentWithRole[]> {
        const response: AxiosResponse<AssignmentWithRole[]> = await api.get(`/authorize/users/${userId}/assignments`)
        return response.data
    },

    async createAssignment(assignment: AssignmentCreate): Promise<Assignment> {
        const response: AxiosResponse<Assignment> = await api.post('/authorize/assignments', assignment)
        return response.data
    },

    async deleteAssignment(id: number): Promise<void> {
        await api.delete(`/authorize/assignments/${id}`)
    },

    async switchRole(roleId: number): Promise<TokenResponse> {
        const response: AxiosResponse<TokenResponse> = await api.post('/authorize/switch-role', { role_id: roleId })
        return response.data
    },

    async setDefaultAssignment(assignmentId: number): Promise<Assignment> {
        const response: AxiosResponse<Assignment> = await api.put(`/authorize/assignments/${assignmentId}/default`)
        return response.data
    }
}
