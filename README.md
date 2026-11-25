# mercator-certs

Application web en **lecture seule** pour consulter les certificats saisis dans
[Mercator](https://github.com/sourcentis/mercator), via sa **couche REST** (Laravel Passport).

## Ce que fait l'app
- Récupère `GET /api/certificates?include=logicalServers,applications` avec un compte de service
  (token obtenu par `POST /api/login`, mis en cache et renouvelé automatiquement sur 401).
- Calcule l'échéance de chaque certificat (expiré / ≤ 30 j / ≤ 90 j / valide / révoqué / sans date).
- Tableau triable, recherche plein texte, filtres échéance et type, fiche détail, export CSV (Excel FR).
- Cache mémoire (`CACHE_TTL`, 300 s) ; bouton **Actualiser** pour forcer la relecture.
  Si Mercator est injoignable, les dernières données en cache restent affichées avec un bandeau d'alerte.

## Rapport de contrôle PDF (preuve)
Bouton **Rapport PDF** : saisir le nom du contrôleur (+ commentaire, périmètre) puis générer.
- Les données sont **relues en direct dans Mercator** (cache ignoré). Si Mercator est injoignable, le rapport
  est **refusé** : on n'atteste pas d'un contrôle sur des données périmées.
- Le PDF (A4 paysage, palette corporate) contient : attestation datée, contrôleur, source, seuils, synthèse,
  points d'attention (action attendue), inventaire complet, bloc de signature contrôleur / validation,
  référence unique `CTRL-AAAAMMJJ-HHMMSS-xxxx` et **empreinte SHA-256** des données.
- Chaque rapport est **archivé** dans le volume `/data/reports` : `<réf>.pdf`, `<réf>.json` (données
  sources exactes) et un journal `index.jsonl`. L'historique est consultable dans l'application.
- Vérification d'intégrité : `sha256sum CTRL-....json` doit donner l'empreinte imprimée dans le PDF.
- **Sauvegarder le volume `certs-data`** : c'est lui qui constitue la piste d'audit.

## Catégories (certificat / licence / domaine)
Mercator stocke tout dans l'entité « certificats » ; l'app classe chaque élément d'après la colonne **type** :
contient `domain` ou `dns` → **Domaine** ; contient `licen` → **Licence** ; sinon → **Certificat**.
Mots-clés ajustables : `DOMAIN_TYPE_KEYWORDS`, `LICENSE_TYPE_KEYWORDS`. Onglets, tuiles, filtres, export CSV
et rapport PDF (périmètre au choix) suivent cette classification.

## Liens vers Mercator
Renseigner `MERCATOR_PUBLIC_URL` (URL de Mercator joignable depuis le navigateur des utilisateurs, pas
l'adresse interne Docker) pour activer, sur chaque ligne et dans la fiche détail, un lien direct vers
l'écran d'édition du certificat/de la licence dans Mercator (`/admin/certificates/{id}/edit`), où l'on
met à jour les dates de validité lors d'un renouvellement. Les droits de l'utilisateur dans Mercator
s'appliquent (connexion requise).

## Prérequis côté Mercator
1. L'API doit être active (Passport installé ; natif dans l'image Docker de Mercator).
2. Créer un utilisateur de service avec un **rôle en lecture seule** contenant
   `certificate_access` (+ `logical_server_access`, `application_access` pour les noms liés).
   Sans ce droit l'API répond 403 et l'app l'indique explicitement.

## Démarrage
```bash
cp .env.example .env     # renseigner MERCATOR_URL, MERCATOR_LOGIN, MERCATOR_PASSWORD
docker compose up -d --build
# http://<serveur>:8090
```
Derrière Nginx Proxy Manager : ajouter un hôte (ex. `certs.bpp.local`) vers `mercator-certs:8000`
(même réseau Docker) puis retirer le mapping `ports`.

## Sécurité
- L'app ne fait **aucune écriture** dans Mercator.
- Le nom du contrôleur est saisi librement ; avec `APP_BASIC_USER` actif, le compte de session est aussi
  consigné dans le rapport. Pour une identité vérifiée, brancher une authentification (AD) devant l'app.
- Pas d'authentification utilisateur intégrée : soit protéger en amont (NPM / réseau), soit activer
  `APP_BASIC_USER` / `APP_BASIC_PASSWORD` (HTTP Basic).
- Les données Mercator sont affichées en texte (jamais injectées en HTML).

## Tests
`pip install -r requirements.txt pytest && pytest tests` (utilise un faux Mercator calqué sur le code source).

## Limites connues
- L'API de liste de Mercator n'est pas paginée : OK pour des milliers de certificats, à surveiller au-delà.
- Les noms de serveurs/applications dépendent des droits du compte de service.
