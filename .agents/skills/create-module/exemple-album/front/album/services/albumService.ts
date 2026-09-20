import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export interface Album {
    id: number
    code: string
    titre: string
    auteur: string
    annee: number | null
    nombre_pistes: number | null
    duree: number | null
}

export interface AlbumCreate {
    code: string
    titre: string
    auteur: string
    annee?: number | null
    nombre_pistes?: number | null
    duree?: number | null
}

export interface AlbumUpdate extends Partial<AlbumCreate> { }

export default {
    getAlbums(): Promise<AxiosResponse<Album[]>> {
        return api.get('/albums')
    },
    getAlbum(id: number): Promise<AxiosResponse<Album>> {
        return api.get(`/albums/${id}`)
    },
    createAlbum(album: AlbumCreate): Promise<AxiosResponse<Album>> {
        return api.post('/albums', album)
    },
    updateAlbum(id: number, album: AlbumUpdate): Promise<AxiosResponse<Album>> {
        return api.put(`/albums/${id}`, album)
    },
    deleteAlbum(id: number): Promise<AxiosResponse<void>> {
        return api.delete(`/albums/${id}`)
    }
}
