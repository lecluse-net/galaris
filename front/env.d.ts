/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

declare module 'socket.io-client' {
    export { io, Socket } from 'socket.io-client/dist/socket.io'
}

declare module '*.vue' {
    import type { DefineComponent } from 'vue'
    const component: DefineComponent<{}, {}, any>
    export default component
}

interface ImportMetaEnv {
    readonly VITE_APP_NAME: string
}

interface ImportMeta {
    readonly env: ImportMetaEnv
}
