# Quiz vidéo

Un formateur colle le lien d'une vidéo, le site la transcrit et écrit un questionnaire.
Il relit, publie, puis partage un lien. Les participants laissent leurs coordonnées,
répondent, et le formateur consulte les résultats (export CSV).

## Lancer

1. Copier `.env.example` en `.env`, puis renseigner `ADMIN_PASSWORD` et `ANTHROPIC_API_KEY`.
2. `python -m pip install -r requirements.txt`
3. `python -m uvicorn app.main:app --port 8765`
4. Administration : http://localhost:8765/admin (identifiant `admin`).

## Limites connues

- Le téléchargement YouTube marche depuis un ordinateur personnel, pas depuis la plupart des hébergeurs.
  En cas d'échec, collez la transcription à la main.
- Hors de ce PC, il faut un hébergement HTTPS : mots de passe et coordonnées ne doivent pas transiter en clair.
- Les coordonnées des participants sont des données personnelles (RGPD) : durée de conservation et
  mention d'information à définir avant ouverture au public.
