import { defineStore } from 'pinia'
import albumService, { type Album, type AlbumCreate, type AlbumUpdate } from '../services/albumService'
import { BaseRoom, websocket } from '@/core/websocket'
import { useAuthStore } from '@/core/user/stores/authStore'
import { watch } from 'vue'

interface AlbumState {
    albums: Album[]
    currentAlbum: Album | null
    loading: boolean
    error: unknown
    // Room active pour la souscription websocket (basée sur user_id)
    activeRoom: AlbumRoom | null
    // Flag pour savoir si on est souscrit
    isSubscribed: boolean
    // Watch stop handler
    unwatchAuth: (() => void) | null
}

class AlbumRoom extends BaseRoom {
  readonly className = 'AlbumRoom'
}

export const useAlbumStore = defineStore('album', {
    state: (): AlbumState => ({
        albums: [],
        currentAlbum: null,
        loading: false,
        error: null,
        activeRoom: null,
        isSubscribed: false,
        unwatchAuth: null
    }),
    actions: {
        async fetchAlbums(): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await albumService.getAlbums()
                this.albums = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching albums:', error)
            } finally {
                this.loading = false
            }
        },
        async fetchAlbum(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await albumService.getAlbum(id)
                this.currentAlbum = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching album:', error)
            } finally {
                this.loading = false
            }
        },
        async createAlbum(album: AlbumCreate): Promise<Album> {
            this.loading = true
            this.error = null
            try {
                const response = await albumService.createAlbum(album)
                this.albums.push(response.data)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error creating album:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async updateAlbum(id: number, album: AlbumUpdate): Promise<Album> {
            this.loading = true
            this.error = null
            try {
                const response = await albumService.updateAlbum(id, album)
                const index = this.albums.findIndex(a => a.id === id)
                if (index !== -1) {
                    this.albums[index] = response.data
                }
                this.currentAlbum = response.data
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error updating album:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async deleteAlbum(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                await albumService.deleteAlbum(id)
                this.albums = this.albums.filter(a => a.id !== id)
            } catch (error) {
                this.error = error
                console.error('Error deleting album:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        /**
         * S'abonner aux événements websocket pour les albums de l'utilisateur courant.
         * Le backend émet les événements vers AlbumRoom:user_id (created_by).
         */
        subscribeToUserAlbums() {
            if (this.isSubscribed) {
                return  // Déjà souscrit
            }

            // 1. Récupérer l'user_id de l'utilisateur authentifié
            const authStore = useAuthStore()
            let userId = authStore.user?.id

            // Si pas encore d'utilisateur, on attend qu'il se connecte
            if (!userId) {
                // Arrêter l'ancien watcher s'il existe
                if (this.unwatchAuth) {
                    this.unwatchAuth()
                }

                // Créer un watcher pour s'abonner dès que l'utilisateur est connecté
                this.unwatchAuth = watch(
                    () => authStore.user?.id,
                    (newUserId) => {
                        if (newUserId && !this.isSubscribed) {
                            this._doSubscribe(newUserId)
                        }
                    },
                    { immediate: true }
                )
                return
            }

            // Souscription immédiate si l'utilisateur est déjà connecté
            this._doSubscribe(userId)
        },

        /**
         * Effectue la souscription réelle (appelé quand on a un userId valide)
         */
        _doSubscribe(userId: string | number) {
            if (this.isSubscribed) {
                return
            }

            // 2. Initialiser le socket si ce n'est pas fait
            websocket.createWebsocket()

            // 3. Créer la room basée sur l'user_id
            const room = new AlbumRoom(userId)
            this.activeRoom = room

            // 4. Demander au serveur de rejoindre le salon
            websocket.joinRoom(room)

            // 5. Définir les écouteurs d'événements
            // Le format match le {subject}.{action} du Back
            websocket.onEvent('album', 'create', (response: { data: Album }) => {
                const newAlbum = response.data
                const exists = this.albums.some(a => a.id === newAlbum.id)
                if (!exists) {
                    // Utiliser splice pour garantir la réactivité Vue
                    this.albums.splice(this.albums.length, 0, newAlbum)
                }
            })

            websocket.onEvent('album', 'update', (response: { data: Album }) => {
                const updatedData = response.data
                const index = this.albums.findIndex(a => a.id === updatedData.id)
                if (index !== -1) {
                    // Remplacer l'élément avec splice pour garantir la réactivité
                    this.albums.splice(index, 1, { ...this.albums[index], ...updatedData })
                }
                if (this.currentAlbum?.id === updatedData.id) {
                    this.currentAlbum = { ...this.currentAlbum, ...updatedData }
                }
            })

            websocket.onEvent('album', 'delete', (response: { data: { id: number } }) => {
                const deletedId = response.data.id
                const index = this.albums.findIndex(a => a.id === deletedId)
                if (index !== -1) {
                    // Supprimer avec splice pour garantir la réactivité
                    this.albums.splice(index, 1)
                }
                if (this.currentAlbum?.id === deletedId) {
                    this.currentAlbum = null
                }
            })

            this.isSubscribed = true
        },

        /**
         * Se désabonner (crucial pour éviter les fuites de données)
         */
        unsubscribeFromUserAlbums() {

            // Arrêter le watcher d'authentification
            if (this.unwatchAuth) {
                this.unwatchAuth()
                this.unwatchAuth = null
            }

            if (!this.isSubscribed || !this.activeRoom) {
                return
            }

            // Quitter la room
            websocket.leaveRoom(this.activeRoom)

            this.activeRoom = null
            this.isSubscribed = false
        }
    }
})
