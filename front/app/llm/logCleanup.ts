import { llmCallService } from './services/llmCallService'

export default { key: 'llm', run: () => llmCallService.cleanup() }
