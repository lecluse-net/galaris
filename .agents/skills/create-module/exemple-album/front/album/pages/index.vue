<template>
  <q-page class="q-pa-md">
    <!-- Title Zone -->
    <h1>Albums</h1>
    <q-separator></q-separator>
    <br />
    <!-- End of title Zone -->

    <!-- Bouton ajouter -->
    <div class="row q-mb-md justify-end">
      <q-btn color="primary" icon="add" label="Nouvel Album" @click="openDialog()" />
    </div>

    <q-table
      :rows="albumStore.albums"
      :columns="columns"
      row-key="id"
      :loading="albumStore.loading"
    >
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn flat round color="primary" icon="edit" size="sm" @click="openDialog(props.row)" />
          <q-btn flat round color="negative" icon="delete" size="sm" @click="confirmDelete(props.row)" />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="showDialog">
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">{{ isEdit ? 'Modifier' : 'Ajouter' }} un album</div>
        </q-card-section>

        <q-card-section class="q-pt-none">
          <q-form @submit="onSubmit" class="q-gutter-md">
            <q-input v-model="form.code" autofocus label="Code" filled :rules="[val => !!val || 'Requis']" />
            <q-input v-model="form.titre" label="Titre" filled :rules="[val => !!val || 'Requis']" />
            <q-input v-model="form.auteur" label="Auteur" filled :rules="[val => !!val || 'Requis']" />
            <q-input v-model.number="form.annee" label="Année" type="number" filled />
            <q-input v-model.number="form.nombre_pistes" label="Nombre de pistes" type="number" filled />
            <q-input v-model.number="form.duree" label="Durée (secondes)" type="number" filled />

            <div class="row justify-end q-mt-md">
              <q-btn label="Annuler" color="white" text-color="black" flat v-close-popup />
              <q-btn :label="isEdit ? 'Modifier' : 'Créer'" type="submit" color="primary" :loading="albumStore.loading" />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

    <q-dialog v-model="showDeleteDialog">
      <q-card>
        <q-card-section class="row items-center">
          <q-avatar icon="warning" color="warning" text-color="white" />
          <span class="q-ml-sm">Voulez-vous vraiment supprimer cet album ?</span>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat label="Annuler" color="primary" v-close-popup />
          <q-btn flat label="Supprimer" color="negative" @click="deleteAlbum" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, onMounted, onUnmounted, reactive } from 'vue'
import { useAlbumStore } from '../stores/albumStore'
import { useQuasar } from 'quasar'

const $q = useQuasar()
const albumStore = useAlbumStore()

const columns = [
  { name: 'code', label: 'Code', field: 'code', sortable: true, align: 'left' },
  { name: 'titre', label: 'Titre', field: 'titre', sortable: true, align: 'left' },
  { name: 'auteur', label: 'Auteur', field: 'auteur', sortable: true, align: 'left' },
  { name: 'annee', label: 'Année', field: 'annee', sortable: true },
  { name: 'pistes', label: 'Pistes', field: 'nombre_pistes', sortable: true },
  { name: 'duree', label: 'Durée (s)', field: 'duree', sortable: true },
  { name: 'actions', label: 'Actions', field: 'actions', align: 'center' }
]

const showDialog = ref(false)
const showDeleteDialog = ref(false)
const isEdit = ref(false)
const albumToDelete = ref(null)

const form = reactive({
  id: null,
  code: '',
  titre: '',
  auteur: '',
  annee: null,
  nombre_pistes: null,
  duree: null
})

const resetForm = () => {
  form.id = null
  form.code = ''
  form.titre = ''
  form.auteur = ''
  form.annee = null
  form.nombre_pistes = null
  form.duree = null
}

const openDialog = (album = null) => {
  if (album) {
    isEdit.value = true
    Object.assign(form, album)
  } else {
    isEdit.value = false
    resetForm()
  }
  showDialog.value = true
}

const onSubmit = async () => {
  try {
    if (isEdit.value) {
      await albumStore.updateAlbum(form.id, form)
      $q.notify({ type: 'positive', message: 'Album modifié avec succès' })
    } else {
      await albumStore.createAlbum(form)
      $q.notify({ type: 'positive', message: 'Album créé avec succès' })
    }
    showDialog.value = false
  } catch (error) {
    $q.notify({ type: 'negative', message: 'Une erreur est survenue' })
  }
}

const confirmDelete = (album) => {
  albumToDelete.value = album
  showDeleteDialog.value = true
}

const deleteAlbum = async () => {
  if (albumToDelete.value) {
    try {
      await albumStore.deleteAlbum(albumToDelete.value.id)
      $q.notify({ type: 'positive', message: 'Album supprimé avec succès' })
    } catch (error) {
      $q.notify({ type: 'negative', message: 'Impossible de supprimer l\'album' })
    }
  }
}

onMounted(() => {
  albumStore.fetchAlbums()
  // Souscription aux événements websocket pour les albums de l'utilisateur
  albumStore.subscribeToUserAlbums()
})

onUnmounted(() => {
  // Se désabonner pour éviter les fuites de mémoire
  albumStore.unsubscribeFromUserAlbums()
})
</script>
