import { defineStore } from 'pinia'

import {
    skillService,
    type SkillAgent,
    type SkillCategory,
    type Skill,
    type SkillCreate,
    type SkillFile,
    type SkillImportResult,
    type SkillRescanResult,
    type SkillUpdate,
} from '../services/skillService'

interface SkillState {
    skills: Skill[]
    agents: SkillAgent[]
    categories: SkillCategory[]
    currentSkill: Skill | null
    currentFiles: SkillFile[]
    currentContent: string
    currentPath: string | null
    loading: boolean
    contentLoading: boolean
    error: unknown
}

export const useSkillStore = defineStore('skill', {
    state: (): SkillState => ({
        skills: [],
        agents: [],
        categories: [],
        currentSkill: null,
        currentFiles: [],
        currentContent: '',
        currentPath: null,
        loading: false,
        contentLoading: false,
        error: null,
    }),
    getters: {
        getById: state => (id: number): Skill | undefined => state.skills.find(skill => skill.id === id),
    },
    actions: {
        _replaceSkill(skill: Skill): void {
            const index = this.skills.findIndex(item => item.id === skill.id)
            if (index === -1) this.skills.push(skill)
            else this.skills.splice(index, 1, skill)
            if (this.currentSkill?.id === skill.id) this.currentSkill = skill
        },
        async fetchSkills(): Promise<void> {
            this.loading = true
            this.error = null
            try {
                this.skills = (await skillService.getSkills()).data
            } catch (error) {
                this.error = error
                console.error('Error fetching skills:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async fetchAgents(): Promise<void> {
            try {
                this.agents = (await skillService.getAgents()).data
            } catch (error) {
                this.error = error
                console.error('Error fetching agents for skills:', error)
                throw error
            }
        },
        async fetchCategories(): Promise<void> {
            try {
                this.categories = (await skillService.getCategories()).data
            } catch (error) {
                this.error = error
                console.error('Error fetching skill categories:', error)
                throw error
            }
        },
        async createCategory(label: string): Promise<SkillCategory> {
            const result = (await skillService.createCategory(label)).data
            this.categories.push(result.category)
            this.categories.sort((left, right) => left.label.localeCompare(right.label))
            return result.category
        },
        async updateCategory(id: number, label: string): Promise<SkillCategory> {
            const result = (await skillService.updateCategory(id, label)).data
            const index = this.categories.findIndex(category => category.id === id)
            if (index !== -1) this.categories.splice(index, 1, result.category)
            for (const skill of this.skills) {
                if (skill.category_id === id) skill.category_label = result.category.label
            }
            this.categories.sort((left, right) => left.label.localeCompare(right.label))
            return result.category
        },
        async deleteCategory(id: number): Promise<void> {
            const result = (await skillService.deleteCategory(id)).data
            this.categories = this.categories.filter(category => category.id !== id)
            for (const skill of this.skills) {
                if (skill.category_id === id) {
                    skill.category_id = null
                    skill.category_label = null
                }
            }
            await Promise.all(
                result.affected_agent_ids.map(agentId => skillService.syncAgent(agentId))
            )
        },
        async assignCategory(
            skillId: number,
            categoryId: number | null,
        ): Promise<{ skill: Skill; synchronized: boolean }> {
            const previousCategoryId = this.skills.find(skill => skill.id === skillId)?.category_id
            const result = (await skillService.assignCategory(skillId, categoryId)).data
            this._replaceSkill(result.skill)

            if (previousCategoryId !== undefined && previousCategoryId !== result.skill.category_id) {
                const previousCategory = this.categories.find(
                    category => category.id === previousCategoryId
                )
                if (previousCategory) {
                    previousCategory.skill_count = Math.max(0, previousCategory.skill_count - 1)
                }
                const nextCategory = this.categories.find(
                    category => category.id === result.skill.category_id
                )
                if (nextCategory) nextCategory.skill_count += 1
            }

            const syncResults = await Promise.allSettled(
                result.affected_agent_ids.map(agentId => skillService.syncAgent(agentId))
            )
            const synchronized = syncResults.every(syncResult => syncResult.status === 'fulfilled')
            if (!synchronized) console.error('Error synchronizing agents after category assignment')
            return { skill: result.skill, synchronized }
        },
        async createSkill(data: SkillCreate): Promise<Skill> {
            this.loading = true
            try {
                const skill = (await skillService.createSkill(data)).data
                this._replaceSkill(skill)
                return skill
            } catch (error) {
                this.error = error
                console.error('Error creating skill:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async updateSkill(id: number, data: SkillUpdate): Promise<Skill> {
            this.loading = true
            try {
                const skill = (await skillService.updateSkill(id, data)).data
                this._replaceSkill(skill)
                return skill
            } catch (error) {
                this.error = error
                console.error('Error updating skill:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async deleteSkill(id: number): Promise<void> {
            this.loading = true
            try {
                const result = (await skillService.deleteSkill(id)).data
                this.skills = this.skills.filter(skill => skill.id !== id)
                if (this.currentSkill?.id === id) this.clearCurrent()
                await Promise.all(
                    result.affected_agent_ids.map(agentId => skillService.syncAgent(agentId))
                )
            } catch (error) {
                this.error = error
                console.error('Error deleting skill:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async importSkill(
            file: File,
            options: { code?: string; label?: string; overwrite?: boolean },
        ): Promise<SkillImportResult> {
            this.loading = true
            try {
                const result = (await skillService.importSkill(file, options)).data
                this._replaceSkill(result.skill)
                return result
            } catch (error) {
                this.error = error
                console.error('Error importing skill:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async rescan(): Promise<SkillRescanResult> {
            this.loading = true
            try {
                const result = (await skillService.rescan()).data
                await this.fetchSkills()
                return result
            } catch (error) {
                this.error = error
                console.error('Error rescanning skill directory:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async openSkill(skill: Skill): Promise<void> {
            this.currentSkill = skill
            this.currentContent = ''
            this.currentPath = null
            this.contentLoading = true
            try {
                this.currentFiles = (await skillService.getFiles(skill.id)).data
                const main = this.currentFiles.find(file => file.path === 'SKILL.md')
                if (main) await this.openFile(main)
            } catch (error) {
                this.error = error
                console.error('Error opening skill:', error)
                throw error
            } finally {
                this.contentLoading = false
            }
        },
        async openFile(file: SkillFile): Promise<void> {
            this.currentPath = file.path
            if (!file.text || !this.currentSkill) {
                this.currentContent = ''
                return
            }
            this.contentLoading = true
            try {
                this.currentContent = (
                    await skillService.getFileContent(this.currentSkill.id, file.path)
                ).data.content
            } catch (error) {
                this.error = error
                console.error('Error reading skill file:', error)
                throw error
            } finally {
                this.contentLoading = false
            }
        },
        async syncAgent(agentId: number): Promise<void> {
            await skillService.syncAgent(agentId)
        },
        async syncExternalAgents(): Promise<boolean> {
            const results = await Promise.allSettled(
                this.agents
                    .filter(agent => agent.driver !== 'internal')
                    .map(agent => skillService.syncAgent(agent.id)),
            )
            const failures = results.filter(result => result.status === 'rejected')
            if (failures.length) {
                console.error(
                    `Error synchronizing updated skill to ${failures.length} external agent(s)`,
                )
            }
            return failures.length === 0
        },
        clearCurrent(): void {
            this.currentSkill = null
            this.currentFiles = []
            this.currentContent = ''
            this.currentPath = null
        },
    },
})
