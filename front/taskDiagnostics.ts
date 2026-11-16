import { defineAsyncView } from '@/core/util/facade'
import { hasAnyPrivilege, labSectionPrivileges } from '@/app/lab/interface'
import type { TaskDiagnosticsContribution } from '@/app/task/contracts'

export default {
  component: defineAsyncView(async () => (await import('@/app/lab')).TaskLabCaptureMenu),
  canUse: hasPrivilege => hasAnyPrivilege(hasPrivilege, [
    labSectionPrivileges.dispatcher[1], labSectionPrivileges.planner[1], labSectionPrivileges.task_executor[1],
  ]),
} satisfies TaskDiagnosticsContribution
