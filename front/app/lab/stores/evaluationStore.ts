import { defineStore } from 'pinia'
import {
  evaluationService,
  type LabConfig,
  type LabTaskReference,
  type LabTaskSummary,
  type TaskAnalysis,
} from '../services/evaluationService'

interface EvaluationState {
  config: LabConfig | null
  tasks: LabTaskReference[]
  candidates: LabTaskSummary[]
  diagnoses: Record<string, TaskAnalysis[]>
  selectedTaskId: string | null
  selectedDiagnosisId: string | null
  loading: boolean
  candidatesLoading: boolean
  diagnosesLoadingTaskId: string | null
  analyzingTaskId: string | null
  error: unknown
}

export const useEvaluationStore = defineStore('evaluationLab', {
  state: (): EvaluationState => ({
    config: null,
    tasks: [],
    candidates: [],
    diagnoses: {},
    selectedTaskId: null,
    selectedDiagnosisId: null,
    loading: false,
    candidatesLoading: false,
    diagnosesLoadingTaskId: null,
    analyzingTaskId: null,
    error: null,
  }),
  getters: {
    selectedReference: state => state.tasks.find(item => item.task_id === state.selectedTaskId) ?? null,
    selectedDiagnoses: state => (
      state.selectedTaskId ? state.diagnoses[state.selectedTaskId] ?? [] : []
    ),
    selectedAnalysis: state => {
      if (!state.selectedTaskId) return null
      const diagnoses = state.diagnoses[state.selectedTaskId] ?? []
      return diagnoses.find(item => item.id === state.selectedDiagnosisId) ?? diagnoses[0] ?? null
    },
  },
  actions: {
    async loadAll(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const [config, tasks] = await Promise.all([
          evaluationService.config(),
          evaluationService.tasks(),
        ])
        this.$patch(state => {
          state.config = config.data
          state.tasks = tasks.data
          if (!state.selectedTaskId || !state.tasks.some(item => item.task_id === state.selectedTaskId)) {
            state.selectedTaskId = state.tasks[0]?.task_id ?? null
          }
        })
        if (this.selectedTaskId) await this.loadDiagnoses(this.selectedTaskId)
      } catch (error) {
        this.error = error
        throw error
      } finally {
        this.loading = false
      }
    },
    async loadCandidates(search = ''): Promise<void> {
      this.candidatesLoading = true
      try {
        this.candidates = (await evaluationService.candidates(search)).data
      } finally {
        this.candidatesLoading = false
      }
    },
    async addTask(taskId: string): Promise<void> {
      const reference = (await evaluationService.addTask(taskId)).data
      this.$patch(state => {
        const existing = state.tasks.findIndex(item => item.task_id === taskId)
        if (existing >= 0) state.tasks.splice(existing, 1, reference)
        else state.tasks.unshift(reference)
        state.candidates = state.candidates.filter(item => item.task_id !== taskId)
        state.selectedTaskId = taskId
      })
      await this.loadDiagnoses(taskId)
    },
    async removeTask(taskId: string): Promise<void> {
      await evaluationService.removeTask(taskId)
      this.$patch(state => {
        state.tasks = state.tasks.filter(item => item.task_id !== taskId)
        if (state.selectedTaskId === taskId) {
          state.selectedTaskId = state.tasks[0]?.task_id ?? null
          state.selectedDiagnosisId = state.selectedTaskId
            ? state.diagnoses[state.selectedTaskId]?.[0]?.id ?? null
            : null
        }
      })
    },
    selectTask(taskId: string): void {
      this.selectedTaskId = taskId
      this.selectedDiagnosisId = this.diagnoses[taskId]?.[0]?.id ?? null
    },
    selectDiagnosis(diagnosisId: string): void {
      this.selectedDiagnosisId = diagnosisId
    },
    async loadDiagnoses(taskId: string): Promise<void> {
      this.diagnosesLoadingTaskId = taskId
      try {
        const diagnoses = (await evaluationService.diagnoses(taskId)).data
        this.$patch(state => {
          state.diagnoses[taskId] = diagnoses
          if (state.selectedTaskId === taskId) {
            const selectionStillExists = diagnoses.some(
              item => item.id === state.selectedDiagnosisId,
            )
            if (!selectionStillExists) state.selectedDiagnosisId = diagnoses[0]?.id ?? null
          }
        })
      } finally {
        if (this.diagnosesLoadingTaskId === taskId) this.diagnosesLoadingTaskId = null
      }
    },
    async analyzeTask(
      taskId: string,
      language: 'fr' | 'en' | 'zh',
      userContext: string,
    ): Promise<TaskAnalysis> {
      this.analyzingTaskId = taskId
      try {
        const diagnosis = (await evaluationService.analyzeTask(taskId, language, userContext)).data
        this.$patch(state => {
          const history = state.diagnoses[taskId] ?? []
          state.diagnoses[taskId] = [
            diagnosis,
            ...history.filter(item => item.id !== diagnosis.id),
          ]
          state.selectedDiagnosisId = diagnosis.id
        })
        return diagnosis
      } finally {
        this.analyzingTaskId = null
      }
    },
  },
})
