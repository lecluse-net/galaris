import { taskService } from './services/taskService'

export default { key: 'tasks', run: () => taskService.cleanup() }
