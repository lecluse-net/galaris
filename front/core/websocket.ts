import { ref } from 'vue'
import { io, Socket } from 'socket.io-client'
import { jwtDecode } from 'jwt-decode'
import { api, AUTH_TOKEN_CHANGED_EVENT, getStoredAccessToken } from './api'

// Payload for the server welcome event.
interface WelcomeData {
    message: string
}

function tokenIdentity(token: string | null): string | null {
    if (!token) return null
    try {
        const { sub, role_id } = jwtDecode<{ sub?: string; role_id?: number }>(token)
        return JSON.stringify([sub, role_id])
    } catch {
        return token
    }
}

export abstract class BaseRoom {
    abstract readonly className: string
    constructor(public readonly id?: string | number) { }

    // Render the room identifier expected by the backend.
    toString(): string {
        return this.id ? `${this.className}:${this.id}` : this.className
    }
}

class WebSocket {
    private _socket: Socket | null = null
    private _isConnected = ref(false)
    private _displayedRoomName: string | null = null
    private _authIdentity: string | null = null
    private _desiredRooms = new Set<string>()
    private _eventListeners = new Map<string, Set<(data: any) => void>>()

    constructor() {
        window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, (event: Event) => {
            const token = (event as CustomEvent<string | null>).detail
            if (!this._socket) return

            if (!token) {
                this._desiredRooms.clear()
                this._displayedRoomName = null
                this._authIdentity = null
                this._socket.disconnect()
                this._isConnected.value = false
                return
            }

            if (this._socket.connected && tokenIdentity(token) !== this._authIdentity) {
                this._socket.disconnect()
            }

            if (!this._socket.active) {
                this._socket.connect()
            }
        })
    }

    /**
     * Create and initialize the WebSocket connection.
     */
    createWebsocket(): Socket {
        // Reuse the existing connection.
        if (this._socket) {
            // active includes an in-flight handshake and automatic reconnection.
            if (getStoredAccessToken() && !this._socket.active) {
                this._socket.connect()
            }
            //console.log('🔌 WebSocket already initialized, reusing existing socket')
            return this._socket
        }

        // Otherwise create a new connection.
        //console.log('🔌 Initializing WebSocket connection...')
        this._socket = io({
            autoConnect: false,
            auth: (callback: (data: { token?: string; events: string[] }) => void) => {
                const token = getStoredAccessToken()
                this._authIdentity = tokenIdentity(token)
                callback({ ...(token ? { token } : {}), events: [...this._eventListeners.keys()] })
            },
        })

        // Listen for native Socket.IO events.
        this._socket.on('connect', () => {
            // A role can change while the previous handshake is still in flight.
            if (this._authIdentity !== tokenIdentity(getStoredAccessToken())) {
                this._socket?.disconnect().connect()
                return
            }
            this._isConnected.value = true
            this.syncEventSubscriptions()
            for (const room of this._desiredRooms) this._socket?.emit('room.join', { room })
            this._socket?.emit('room.display', { room: this._displayedRoomName })
            // console.log(`WebSocket connected with ID ${this._socket?.id}`)
        })

        this._socket.on('disconnect', (reason: string) => {
            this._isConnected.value = false
            if (reason === 'io server disconnect' && getStoredAccessToken()) {
                // The HTTP client owns refresh/revocation handling. A valid newer
                // token reconnects directly; a revoked session remains signed out.
                void api.get('/auth/me').then(() => {
                    if (getStoredAccessToken() && !this._socket?.active) this._socket?.connect()
                }).catch(() => undefined)
            }
            // console.log('WebSocket disconnected')
        })

        // Listen for the custom event sent by the server.
        this._socket.on('welcome', (_data: WelcomeData) => {
            //console.log('📨 Message from server :', data.message)
        })

        for (const [eventName, listeners] of this._eventListeners) {
            for (const listener of listeners) this._socket.on(eventName, listener)
        }

        if (getStoredAccessToken()) {
            this._socket.connect()
        }

        return this._socket
    }

    /**
     * Join a room (for example, "AlbumRoom:123").
     */
    joinRoom(room: BaseRoom): void {
        const roomStr = room.toString()
        if (this._desiredRooms.has(roomStr)) return
        this._desiredRooms.add(roomStr)
        if (this._socket?.connected) {
            this._socket.emit('room.join', { room: roomStr })
            //console.log(`🚪 JOIN ROOM: ${roomStr}`)
        }
    }

    /**
     * Leave a room.
     */
    leaveRoom(room: BaseRoom): void {
        const roomStr = room.toString()
        this._desiredRooms.delete(roomStr)
        if (this._socket?.connected) {
            this._socket.emit('room.leave', { room: roomStr })
            //console.log(`🚪 LEAVE ROOM: ${roomStr}`)
        } else {
            //console.warn(`⚠️ Cannot leave room ${roomStr}: socket not connected`)
        }
    }

    /** Publish the one resource room that is actually visible in this browser tab. */
    setDisplayedRoom(room: BaseRoom | null): void {
        const roomName = room?.toString() ?? null
        if (roomName === this._displayedRoomName) return
        this._displayedRoomName = roomName
        if (this._socket?.connected) {
            this._socket.emit('room.display', { room: roomName })
        }
    }

    /**
     * Listen for a specific event (subject.action).
     */
    onEvent(subject: string, action: string, callback: (data: any) => void): void {
        const eventName = `${subject}.${action}`
        const listeners = this._eventListeners.get(eventName) ?? new Set()
        if (listeners.has(callback)) return
        const first = listeners.size === 0
        listeners.add(callback)
        this._eventListeners.set(eventName, listeners)
        this._socket?.on(eventName, callback)
        if (first) this.syncEventSubscriptions()
    }

    /**
     * Remove an event listener.
     */
    offEvent(subject: string, action: string, callback?: (data: any) => void): void {
        const eventName = `${subject}.${action}`
        const listeners = this._eventListeners.get(eventName)
        if (!listeners) return
        if (callback) {
            this._socket?.off(eventName, callback)
            listeners.delete(callback)
        } else {
            for (const listener of listeners) this._socket?.off(eventName, listener)
            listeners.clear()
        }
        if (listeners.size === 0) {
            this._eventListeners.delete(eventName)
            this.syncEventSubscriptions()
        }
    }

    /** Replace the server's interest list when the first/last consumer changes. */
    private syncEventSubscriptions(): void {
        if (this._socket?.connected) {
            this._socket.emit('events.subscribe', { events: [...this._eventListeners.keys()] })
        }
    }

    /** Run a callback after every successful initial connection or reconnection. */
    onConnect(callback: () => void): void {
        this._socket?.on('connect', callback)
    }

    /** Remove one connection callback without disturbing other consumers. */
    offConnect(callback: () => void): void {
        this._socket?.off('connect', callback)
    }

    /**
     * Return the reactive connection state.
     */
    get isConnected() {
        return this._isConnected
    }

    /**
     * Return the Socket.IO instance.
     */
    get socket() {
        return this._socket
    }
}

// Shared singleton.
export const websocket = new WebSocket()
