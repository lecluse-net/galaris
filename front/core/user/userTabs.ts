import type { Component } from 'vue'
import { modules as activeModules } from '@/modules'
export interface UserTabContribution { name: string; labelKey: string; icon: string; privilege: string; component: Component; formOnly?: boolean }
const sources=import.meta.glob<{default:UserTabContribution}>('../../app/*/userTab.ts',{eager:true})
export const userTabs=Object.entries(sources).filter(([path])=>activeModules.includes(`app/${path.split('/')[3]}`)).map(([,module])=>module.default)
