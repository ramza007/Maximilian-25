import os, requests

API3 = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p"

class TMDBClient:
    def __init__(self, bearer: str | None = None, api_key: str | None = None, language="en-US"):
        if not bearer and not api_key:
            raise RuntimeError("Set TMDB_BEARER or TMDB_API_KEY in your environment.")
        self.bearer = bearer
        self.api_key = api_key
        self.language = language

    def _headers(self):
        return {"Authorization": f"Bearer {self.bearer}"} if self.bearer else {}

    def _get(self, path, **params):
        if self.api_key and "api_key" not in params:
            params["api_key"] = self.api_key
        if "language" not in params:
            params["language"] = self.language
        r = requests.get(f"{API3}{path}", headers=self._headers(), params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def _poster_url(self, poster_path, size="w500"):
        return f"{IMG_BASE}/{size}{poster_path}" if poster_path else None

    def search(self, query: str, page=1):
        data = self._get("/search/multi", query=query, include_adult=False, page=page)
        results = []
        for item in data.get("results", []):
            media = item.get("media_type")
            if media not in ("movie", "tv"):
                continue
            kind = "movie" if media == "movie" else "series"
            title = item.get("title") or item.get("name") or "Untitled"
            poster = self._poster_url(item.get("poster_path"))
            year = None
            date = item.get("release_date") or item.get("first_air_date")
            if date:
                year = date.split("-", 1)[0]
            results.append({
                "kind": kind,
                "id": item["id"],
                "title": title,
                "year": year,
                "overview": item.get("overview"),
                "poster": poster
            })
        return results

    def get_movie(self, movie_id: int):
        d = self._get(f"/movie/{movie_id}")
        # fetch credits separately (more reliable than append)
        try:
            credits = self._get(f"/movie/{movie_id}/credits")
        except Exception:
            credits = {}

        cast = []
        for p in (credits or {}).get("cast", [])[:20]:
            cast.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "character": p.get("character"),
                "photo": self._profile_url(p.get("profile_path")),
            })

        title = d.get("title") or d.get("name") or "Untitled"
        poster = self._poster_url(d.get("poster_path"))
        genres = [g["name"] for g in d.get("genres", []) if g.get("name")]
        companies = [c["name"] for c in d.get("production_companies", []) if c.get("name")]
        runtime = (d.get("runtime") or (d.get("episode_run_time") or [None])[0])
        year = (d.get("release_date") or "").split("-", 1)[0] or None

        return {
            "id": d.get("id"),
            "kind": "movie",
            "title": title,
            "poster": poster,
            "overview": d.get("overview"),
            "year": year,
            "status": d.get("status"),
            "genres": genres,
            "studios": companies,
            "runtime": runtime,
            "rating": d.get("vote_average"),
            "cast": cast,
        }


    def _normalize_detail(self, d, kind):
        title = d.get("title") or d.get("name") or "Untitled"
        poster = self._poster_url(d.get("poster_path"))
        genres = [g["name"] for g in d.get("genres", []) if g.get("name")]
        companies = [c["name"] for c in d.get("production_companies", []) if c.get("name")]
        runtime = (d.get("runtime") or (d.get("episode_run_time") or [None])[0])
        year = None
        date = d.get("release_date") or d.get("first_air_date")
        if date:
            year = date.split("-", 1)[0]
        return {
            "id": d.get("id"),
            "kind": kind,
            "title": title,
            "poster": poster,
            "overview": d.get("overview"),
            "year": year,
            "status": d.get("status"),
            "genres": genres,
            "studios": companies,
            "runtime": runtime,
            "rating": d.get("vote_average"),
            "airs": None
        }


    def _profile_url(self, path, size="w185"):
        return f"{IMG_BASE}/{size}{path}" if path else None

    def get_series(self, tv_id: int):
        # Base details
        d = self._get(f"/tv/{tv_id}")
        title = d.get("name") or d.get("title") or "Untitled"
        poster = self._poster_url(d.get("poster_path"))
        genres = [g["name"] for g in d.get("genres", []) if g.get("name")]
        companies = [c["name"] for c in d.get("production_companies", []) if c.get("name")]
        year = (d.get("first_air_date") or "").split("-", 1)[0] or None

        # Credits: try aggregate_credits, fall back to credits
        credits = {}
        try:
            credits = self._get(f"/tv/{tv_id}/aggregate_credits")
        except Exception:
            try:
                credits = self._get(f"/tv/{tv_id}/credits")
            except Exception:
                credits = {}

        cast_src = (credits or {}).get("cast", []) or []
        cast = []
        for p in cast_src[:20]:
            # aggregate_credits uses roles=[{character:...}], credits uses character="..."
            character = None
            if isinstance(p.get("roles"), list) and p["roles"]:
                character = p["roles"][0].get("character")
            elif isinstance(p.get("character"), str):
                character = p["character"]
            cast.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "character": character,
                "photo": self._profile_url(p.get("profile_path")),
            })

        return {
            "id": d.get("id"),
            "kind": "series",
            "title": title,
            "poster": poster,
            "overview": d.get("overview"),
            "year": year,
            "genres": genres,
            "studios": companies,
            "cast": cast,
        }

