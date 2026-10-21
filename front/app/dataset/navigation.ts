import type { NavigationTree } from '@/core/navigation'
const navigation: NavigationTree = {
  knowledge: { children: { datasets: { label: 'datasets.title', description: 'datasets.description', icon: 'data_object', order: 14, to: '/dataset', privileges: ['DATASET_READ', 'DATASET_EDIT', 'DATASET_ADMIN'] } } },
}
export default navigation
