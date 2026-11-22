# Quiz vidéo

Un formateur colle le texte d'une vidéo, le site écrit un questionnaire à choix multiples avec l'IA.
Il le relit, le publie, puis partage un lien. Les participants laissent leurs coordonnées,
regardent la vidéo, répondent, et le formateur consulte les résultats (export CSV).

## Mettre en ligne gratuitement : Render + Neon + Gemini

Trois comptes gratuits, à créer vous-même.

1. **Clé Gemini** : sur https://aistudio.google.com/apikey, « Create API key ». Gardez-la de côté.
2. **Base Neon** : sur https://neon.tech, créez un projet, puis copiez la « connection string »
   qui commence par `postgresql://`.
3. **Site Render** : sur https://render.com, connectez-vous avec GitHub, puis
   « New » → « Blueprint » → choisissez ce dépôt. Render lit `render.yaml` et demande :
   - `ADMIN_PASSWORD` : le mot de passe de la page `/admin` (identifiant `admin`) ;
   - `GEMINI_API_KEY` : la clé de l'étape 1 ;
   - `DATABASE_URL` : la connection string de l'étape 2.
4. L'adresse du site s'affiche en haut de la page Render, par exemple `https://quiz-video.onrender.com`.
   L'administration est sur `/admin`.

Bon à savoir, offre gratuite :
- le site s'endort après 15 minutes sans visite, le premier visiteur attend alors environ 50 secondes ;
- Gemini gratuit a une limite de requêtes par jour, largement suffisante pour créer des questionnaires ;
- en ligne, le site ne télécharge pas les vidéos : collez la transcription
  (sur YouTube, sous la vidéo, « Afficher la transcription »).

## Lancer sur votre PC

1. Copier `.env.example` en `.env` et renseigner `ADMIN_PASSWORD` et `GEMINI_API_KEY`.
   Laisser `DATABASE_URL` vide pour utiliser une base locale (SQLite).
2. `python -m pip install -r requirements-local.txt`
3. `python -m uvicorn app.main:app --port 8765`
4. Administration : http://localhost:8765/admin

Sur votre PC, le site peut aussi télécharger et transcrire la vidéo à partir de son lien (yt-dlp et Whisper).

## Tests

`python -m pytest`

## Données personnelles

Les coordonnées des participants sont des données personnelles (RGPD) : fixez une durée de conservation
et indiquez qui les reçoit avant d'ouvrir le site au public. La police Montserrat est chargée depuis
Google Fonts, ce qui transmet l'adresse IP des visiteurs à Google : pour l'éviter, hébergez la police
dans `app/static`.
