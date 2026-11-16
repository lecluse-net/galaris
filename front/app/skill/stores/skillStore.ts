import { toRaw } from 'vue'
import { withSessionScope } from '@/core/util/facade'
import { defineStore } from 'pinia'
import { sessionGeneration } from '@/core/api'

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

const selections = new WeakMap<object, symbol>()
function beginSelection(store: object): () => boolean {
    const selection = Symbol('skill-selection'), session = sessionGeneration()
    selections.set(toRaw(store), selection)
    return () => selections.get(toRaw(store)) === selection && session === sessionGeneration()
}

export const useSkillStore = withSessionScope(defineStore('skill', {
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
        async setSkillEnabled(skill: Skill, enabled: boolean): Promise<void> {
            const result = await skillService.setSkillEnabled(skill.id, enabled, skill.revision)
            this._replaceSkill(result.data)
        },
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
            await skillService.deleteCategory(id)
            this.categories = this.categories.filter(category => category.id !== id)
            for (const skill of this.skills) {
                if (skill.category_id === id) {
                    skill.category_id = null
                    skill.category_label = null
                }
            }
        },
        async assignCategory(
            skillId: number,
            categoryId: number | null,
        ): Promise<Skill> {
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

            return result.skill
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
                await skillService.deleteSkill(id)
                this.skills = this.skills.filter(skill => skill.id !== id)
                if (this.currentSkill?.id === id) this.clearCurrent()
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
        async openSkill(skill: Skill): Promise<boolean> {
            const current = beginSelection(this)
            this.currentSkill = skill
            this.currentFiles = []
            this.currentContent = ''
            this.currentPath = null
            this.contentLoading = true
            this.error = null
            try {
                const files = (await skillService.getFiles(skill.id)).data
                if (!current()) return false
                const main = files.find(file => file.path === 'SKILL.md' && file.text)
                const content = main ? (await skillService.getFileContent(skill.id, main.path)).data.content : ''
                if (!current()) return false
                this.currentFiles = files
                this.currentPath = main?.path ?? null
                this.currentContent = content
                return true
            } catch (error) {
                if (!current()) return false
                this.error = error
                console.error('Error opening skill:', error)
                throw error
            } finally {
                if (current()) this.contentLoading = false
            }
        },
        async openFile(file: SkillFile): Promise<void> {
            const current = beginSelection(this), skillId = this.currentSkill?.id
            this.currentPath = file.path
            this.currentContent = ''
            this.error = null
            if (!file.text || skillId === undefined) {
                this.contentLoading = false
                return
            }
            this.contentLoading = true
            try {
                const result = await skillService.getFileContent(skillId, file.path)
                if (current()) this.currentContent = result.data.content
            } catch (error) {
                if (!current()) return
                this.error = error
                console.error('Error reading skill file:', error)
                throw error
            } finally {
                if (current()) this.contentLoading = false
            }
        },
        clearCurrent(): void {
            selections.delete(toRaw(this))
            this.currentSkill = null
            this.currentFiles = []
            this.currentContent = ''
            this.currentPath = null
            this.contentLoading = false
        },
    },
}), { flags: { fetchSkills: 'loading', createSkill: 'loading', updateSkill: 'loading',
    deleteSkill: 'loading', importSkill: 'loading', rescan: 'loading' } })
