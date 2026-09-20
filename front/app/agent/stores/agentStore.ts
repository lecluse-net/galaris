import { defineStore } from 'pinia'
import { sessionGeneration } from '@/core/api'
import { titleLabel } from '../titleLabels'
import { agentService, titleService, agentGroupService, type Agent, type AgentCreate, type AgentUpdate, type Title, type TitleCreate, type TitleUpdate, type AgentGroup, type AgentGroupCreate, type AgentGroupUpdate } from '../services/agentService'

interface AgentState {
    agents: Agent[]
    titles: Title[]
    groups: AgentGroup[]
    currentAgent: Agent | null
    currentTitle: Title | null
    loading: boolean
    error: unknown
}

const agentRequests = new WeakMap<object, { generation: string; promise: Promise<void> }>()

export const useAgentStore = defineStore('agent', {
    state: (): AgentState => ({
        agents: [],
        titles: [],
        groups: [],
        currentAgent: null,
        currentTitle: null,
        loading: false,
        error: null
    }),
    getters: {
        getTitleLabel: (state) => (titleId: number, translate: (key: string) => string) => {
            const title = state.titles.find(t => t.id === titleId)
            return title ? titleLabel(title.label, translate) : ''
        },
        getGroupName: (state) => (groupId: number | null) => {
            if (groupId === null) return ''
            const group = state.groups.find(g => g.id === groupId)
            return group ? group.name : ''
        },
        sortedGroups: (state) => [...state.groups].sort((a, b) => {
            if (a.order !== b.order) return a.order - b.order
            return a.name.localeCompare(b.name)
        }),
        getFullName: (state) => (agent: Agent, translate: (key: string) => string) => {
            const title = state.titles.find(t => t.id === agent.title_id)
            const displayTitle = title ? titleLabel(title.label, translate) : ''
            return `${displayTitle} ${agent.first_name} ${agent.last_name}`.trim()
        },
        sortedAgents: (state) => [...state.agents].sort((a, b) => {
            if (!a.code && !b.code) return a.id - b.id
            if (!a.code) return 1
            if (!b.code) return -1
            return a.code.localeCompare(b.code)
        })
    },
    actions: {
        // ==================== TITLES ====================
        async fetchTitles(): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await titleService.getTitles()
                this.titles = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching titles:', error)
            } finally {
                this.loading = false
            }
        },
        async fetchTitle(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await titleService.getTitle(id)
                this.currentTitle = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching title:', error)
            } finally {
                this.loading = false
            }
        },
        async createTitle(title: TitleCreate): Promise<Title> {
            this.loading = true
            this.error = null
            try {
                const response = await titleService.createTitle(title)
                this.titles.push(response.data)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error creating title:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async updateTitle(id: number, title: TitleUpdate): Promise<Title> {
            this.loading = true
            this.error = null
            try {
                const response = await titleService.updateTitle(id, title)
                const index = this.titles.findIndex(t => t.id === id)
                if (index !== -1) {
                    this.titles[index] = response.data
                }
                this.currentTitle = response.data
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error updating title:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async deleteTitle(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                await titleService.deleteTitle(id)
                this.titles = this.titles.filter(t => t.id !== id)
            } catch (error) {
                this.error = error
                console.error('Error deleting title:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        // ==================== GROUPS ====================
        async fetchGroups(): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await agentGroupService.getGroups()
                this.groups = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching groups:', error)
            } finally {
                this.loading = false
            }
        },
        async createGroup(group: AgentGroupCreate): Promise<AgentGroup> {
            this.loading = true
            this.error = null
            try {
                const response = await agentGroupService.createGroup(group)
                this.groups.push(response.data)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error creating group:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async updateGroup(id: number, group: AgentGroupUpdate): Promise<AgentGroup> {
            this.loading = true
            this.error = null
            try {
                const response = await agentGroupService.updateGroup(id, group)
                const index = this.groups.findIndex(g => g.id === id)
                if (index !== -1) {
                    this.groups[index] = response.data
                }
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error updating group:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async deleteGroup(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                await agentGroupService.deleteGroup(id)
                this.groups = this.groups.filter(g => g.id !== id)
                // Detach agents locally (backend already did it server-side)
                this.agents = this.agents.map(agent =>
                    agent.group_id === id ? { ...agent, group_id: null } : agent
                )
            } catch (error) {
                this.error = error
                console.error('Error deleting group:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        // ==================== AGENTS ====================
        async fetchAgents(): Promise<void> {
            const generation = sessionGeneration()
            const pending = agentRequests.get(this)
            if (pending?.generation === generation) return pending.promise
            this.loading = true
            this.error = null
            const promise = (async () => {
                try {
                    const response = await agentService.getAgents()
                    if (generation !== sessionGeneration()) return
                    this.agents = response.data
                } catch (error) {
                    if (generation !== sessionGeneration()) return
                    this.agents = []
                    this.error = error
                    console.error('Error fetching agents:', error)
                } finally {
                    if (generation === sessionGeneration()) this.loading = false
                    if (agentRequests.get(this)?.generation === generation) agentRequests.delete(this)
                }
            })()
            agentRequests.set(this, { generation, promise })
            return promise
        },
        async fetchAgent(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await agentService.getAgent(id)
                this.currentAgent = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching agent:', error)
            } finally {
                this.loading = false
            }
        },
        async createAgent(agent: AgentCreate): Promise<Agent> {
            this.loading = true
            this.error = null
            try {
                const response = await agentService.createAgent(agent)
                this.agents.push(response.data)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error creating agent:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async updateAgent(id: number, agent: AgentUpdate): Promise<Agent> {
            this.loading = true
            this.error = null
            try {
                const response = await agentService.updateAgent(id, agent)
                const index = this.agents.findIndex(agent => agent.id === id)
                if (index !== -1) {
                    this.agents.splice(index, 1, response.data)
                }
                this.currentAgent = response.data
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error updating agent:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async deleteAgent(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                await agentService.deleteAgent(id)
                this.agents = this.agents.filter(agent => agent.id !== id)
            } catch (error) {
                this.error = error
                console.error('Error deleting agent:', error)
                throw error
            } finally {
                this.loading = false
            }
        }
    }
})
