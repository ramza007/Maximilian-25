# Maximilian (Flask + TMDb)
Mobile-first diary, uses TMDb data, and Letterboxd CSV import.

## Quickstart
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add TMDB_BEARER or TMDB_API_KEY
flask --app app.py init-db
flask --app app.py run  # http://127.0.0.1:5000
```

## Import Letterboxd CSV
Visit **/import** and upload your CSV. Expected headers include:
`Date, Name, Year, Letterboxd URI, Rating, Rewatch, Tags, Watched Date`

- Watched Date → saved as `date_watched` (falls back to `Date`).
- Rating 0.5–5 → scaled to 1–10.
- Tags / Rewatch → added to `review` text.
- Poster → best-effort TMDb search by title+year.
- Duplicates allowed.
