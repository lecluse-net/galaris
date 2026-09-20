import type { NavigationTree } from '@/core/navigation'

const navigation: NavigationTree = {
    app: {
        children: {
            album: {
                label: 'nav.album',
                icon: 'album',
                to: '/album',
                order: 1000,
            }
        }
    }
}

export default navigation
