# 0190 — Fichiers HTML et mécanismes standards de pièces jointes

Statut : accepté. Date : 2026-10-15.

Les pages `.html` provenant d'un upload ou d'une URI File Sharing restent des fichiers.
Elles ne sont pas des miniatures et ne justifient aucun stockage privé de prévisualisation.
Le circuit Discussion téléchargeait puis réuploadait leurs octets pour créer une copie
temporaire et un ticket d'une heure. Ce circuit et ses deux routes sont supprimés.

Les PJ HTML suivent le stockage géré, les quotas, les ACL et les téléchargements habituels.
Les miniatures conservent les producteurs et le cache WebP partagés. L'ingestion ne parcourt
pas les URL d'images, styles ou autres dépendances et ne réécrit pas le fichier fourni.
Les anciens temporaires de prévisualisation ne sont pas automatiquement effacés.

Les surfaces Documents et Discussion utilisent le même lecteur de fichier côté navigateur.
Le contenu interactif reste dans un cadre sans origine applicative ; seules les enveloppes
fixes du lecteur peuvent conserver cette origine pour charger leurs assets. Une enveloppe
HTTP statique possède sa propre CSP, afin de ne pas hériter des restrictions JavaScript de
la page applicative tout en conservant ces restrictions sur l'application. Elle ne contient
aucune donnée utilisateur persistée et n'emploie aucun ticket ou nouveau mécanisme d'accès
au fichier : les octets proviennent toujours de la lecture autorisée du domaine.

La validation couvre les octets d'origine, les refus d'accès existants, les miniatures,
l'interaction isolée sous CSP restrictive, le téléchargement, le nouvel onglet et la
réouverture sur petit écran. Les anciens tests des copies HTML temporaires sont retirés
avec ce contrat ; leurs garanties utiles de taille et d'intégrité restent dans le stockage
normal, et l'isolation passe dans les tests navigateur du lecteur partagé.
