from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
from werkzeug.exceptions import abort as wz_abort  # optional alias
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from itertools import groupby
from flask import flash
import re
import unicodedata
from difflib import SequenceMatcher
import os

from tmdb import TMDBClient


app = Flask(__name__)

db_uri = os.getenv("DATABASE_URL", "sqlite:///instance/maximilian.db")
app.config["SQLALCHEMY_DATABASE_URI"] = db_uri


# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DEFAULT_SQLITE = "sqlite:////app/instance/maximilian.db"

db_uri = os.getenv("DATABASE_URL", DEFAULT_SQLITE)

# Normalize heroku-style URLs
if db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

db = SQLAlchemy(app)

# Show a name in the header dropdown (set USER_NAME in .env)
@app.context_processor
def inject_display_name():
    return {"display_name": os.environ.get("USER_NAME", "Turbo")}


# --- Models ---
class DiaryEntry(db.Model):
    __tablename__ = "diary_entries"
    id = db.Column(db.Integer, primary_key=True)
    external_id = db.Column(db.String(128), nullable=False)  # TMDb/TVDB/Letterboxd id/url
    kind = db.Column(db.String(16), nullable=False)         # 'movie' or 'series'
    title = db.Column(db.String(256), nullable=False)
    poster_url = db.Column(db.String(512), nullable=True)
    date_watched = db.Column(db.Date, nullable=True)
    rating = db.Column(db.Integer, nullable=True)           # 1..10 (or None)
    review = db.Column(db.Text, nullable=True)
    release_year = db.Column(db.Integer)  # <-- add this
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "external_id": self.external_id,
            "kind": self.kind,
            "title": self.title,
            "poster_url": self.poster_url,
            "date_watched": self.date_watched.isoformat() if self.date_watched else None,
            "rating": self.rating,
            "review": self.review,
            "created_at": self.created_at.isoformat()
        }

# --- Central error pages ---
@app.errorhandler(404)
def handle_404(e):
    # e.description can be set via abort(404, description="...")
    return render_template("404.html",
                           path=request.path,
                           description=getattr(e, "description", None)), 404

@app.errorhandler(500)
def handle_500(e):
    return render_template("500.html",
                           description=getattr(e, "description", None)), 500

# --- TMDb Client ---
tmdb = TMDBClient(
    bearer=os.environ.get("TMDB_BEARER"),
    api_key=os.environ.get("TMDB_API_KEY")
)

# --- Routes ---
@app.route("/")
def index():
    latest = DiaryEntry.query.order_by(DiaryEntry.created_at.desc()).limit(12).all()
    return render_template("index.html", latest=latest)

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        try:
            results = tmdb.search(q)
        except Exception as e:
            return render_template("search.html", q=q, results=[], error=str(e))
    return render_template("search.html", q=q, results=results, error=None)

@app.route("/item/<kind>/<int:item_id>")
def item_detail(kind, item_id):
    try:
        if kind == "movie":
            item = tmdb.get_movie(item_id)
        else:
            item = tmdb.get_series(item_id)
        return render_template("item.html", item=item)
    except requests.HTTPError as ex:
        status = getattr(getattr(ex, "response", None), "status_code", None)
        if status == 404:
            abort(404, description="We couldn’t find that title on TMDb.")
        # Anything else: treat as server error
        app.logger.exception("TMDb error on %s %s", kind, item_id)
        return render_template("500.html",
                               description="Upstream API error. Please try again."), 500


@app.route("/diary")
def diary():
    entries = (DiaryEntry.query
               .order_by(DiaryEntry.date_watched.desc().nullslast(),
                         DiaryEntry.created_at.desc()).all())
    groups = []
    for date, it in groupby(entries, key=lambda e: e.date_watched):
        groups.append({"date": date, "entries": list(it)})
    return render_template("diary.html", groups=groups)

@app.route("/api/diary", methods=["GET"])
def api_diary_list():
    entries = DiaryEntry.query.order_by(DiaryEntry.created_at.desc()).all()
    return jsonify([e.to_dict() for e in entries])

@app.route("/api/diary", methods=["POST"])
def api_diary_add():
    data = request.get_json(force=True)
    try:
        entry = DiaryEntry(
            external_id=str(data.get("external_id") or ""),
            kind=data["kind"],
            title=data["title"],
            poster_url=data.get("poster_url"),
            date_watched=datetime.fromisoformat(data["date_watched"]).date() if data.get("date_watched") else None,
            rating=int(data["rating"]) if data.get("rating") not in (None, "",) else None,
            review=data.get("review", "")
        )
        db.session.add(entry)
        db.session.commit()
        return jsonify({"ok": True, "entry": entry.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/api/diary/<int:entry_id>", methods=["DELETE"])
def api_diary_delete(entry_id):
    entry = DiaryEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/entry/<int:entry_id>/poster", methods=["POST"])
def set_poster(entry_id):
    e = DiaryEntry.query.get_or_404(entry_id)
    url = (request.form.get("poster_url") or "").strip()
    if url:
        e.poster_url = url
        db.session.commit()
    return redirect(url_for("edit_entry", entry_id=entry_id))


@app.cli.command("migrate-add-release-year")
def migrate_add_release_year():
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    cols = [c['name'] for c in insp.get_columns('diary_entries')]
    if "release_year" not in cols:
        db.session.execute(
            text("ALTER TABLE diary_entries ADD COLUMN release_year INTEGER"))
        db.session.commit()
        print("Added release_year column.")
    else:
        print("release_year already exists.")


# --- Letterboxd CSV Import ---
import csv, io
from datetime import datetime as _dt

def _parse_lb_date(s: str):
    if not s: return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return _dt.strptime(s.strip(), fmt).date()
        except Exception:
            pass
    return None

def _map_lb_rating(s: str):
    # LB 0.5..5 -> 1..10 int
    if not s: return None
    try:
        f = float(str(s).strip())
        if f <= 0: return None
        return int(round(f * 2))
    except Exception:
        return None


@app.route("/import", methods=["GET", "POST"])
def import_letterboxd():
    if request.method == "GET":
        return render_template("import.html")

    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".csv"):
        return render_template("import.html", error="Upload a .csv file from Letterboxd export.")

    text = f.stream.read().decode("utf-8", "ignore")
    reader = csv.DictReader(io.StringIO(text))
    added = errors = 0
    poster_cache: dict[tuple[str, int | None], str | None] = {}

    for row in reader:
        try:
            title = (row.get("Name") or row.get("Title") or "").strip()
            if not title:
                continue

            # <-- capture Letterboxd "Year" (release year)
            release_year = None
            y = (row.get("Year") or "").strip()
            if y.isdigit():
                release_year = int(y)

            lb_uri = (row.get("Letterboxd URI") or row.get(
                "Letterboxd URL") or row.get("Letterboxd Uri") or "").strip()
            watched = _parse_lb_date(
                row.get("Watched Date") or row.get("Date") or "")
            rating = _map_lb_rating(row.get("Rating"))
            tags = (row.get("Tags") or "").strip()
            rewatch = (row.get("Rewatch") or "").strip()
            external_id = f"letterboxd:{lb_uri}" if lb_uri else f"letterboxd:{title}:{release_year or ''}"

            # poster (cache by title+release_year)
            key = (title, release_year)
            poster = poster_cache.get(key)
            if poster is None:
                poster = tmdb_poster_for_movie(title, release_year)
                poster_cache[key] = poster

            review_bits = []
            if tags:
                review_bits.append(f"Tags: {tags}")
            if rewatch.lower().startswith("y"):
                review_bits.append("Rewatch")
            review = " • ".join(review_bits) if review_bits else None

            db.session.add(DiaryEntry(
                external_id=external_id,
                kind="movie",
                title=title,
                poster_url=poster,
                date_watched=watched,
                rating=rating,
                review=review,
                release_year=release_year,   # <-- save it
            ))
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1

    db.session.commit()
    return render_template("import.html", added=added, errors=errors)

# --- PWA files ---
@app.route("/manifest.json")
def manifest():
    from flask import send_from_directory
    return send_from_directory("static", "manifest.json")

@app.route("/sw.js")
def service_worker():
    from flask import send_from_directory, make_response
    resp = make_response(send_from_directory("static", "sw.js"))
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp

# --- CLI ---
@app.cli.command("init-db")
def init_db_cmd():
    """Initialize database tables."""
    db.create_all()
    print("Database initialized.")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)

# Drop database - DANGER
@app.cli.command("drop-db")
def drop_db_cmd():
    db.drop_all()
    db.session.commit()
    print("Dropped all tables.")

# DROP TABLE CONTENTS - SOFT RESET
@app.cli.command("reset-db")
def reset_db_cmd():
    db.drop_all()
    db.create_all()
    print("Database reset.")


@app.route("/entry/<int:entry_id>/edit", methods=["GET", "POST"])
def edit_entry(entry_id):
    e = DiaryEntry.query.get_or_404(entry_id)
    if request.method == "POST":
        f = request.form
        e.title = f.get("title", e.title).strip() or e.title
        d = f.get("date_watched", "").strip()
        e.date_watched = datetime.fromisoformat(d).date() if d else None
        r = f.get("rating", "").strip()
        e.rating = int(r) if r else None
        e.review = f.get("review", "").strip() or None
        db.session.commit()
        # Optional: flash("Updated");
        return redirect(url_for("diary"))
    return render_template("entry_edit.html", e=e)

# Optional JSON update if you want API:
@app.route("/api/diary/<int:entry_id>", methods=["PATCH", "PUT"])
def api_diary_update(entry_id):
    e = DiaryEntry.query.get_or_404(entry_id)
    data = request.get_json(force=True)
    if "title" in data:
        e.title = (data["title"] or e.title).strip()
    if "date_watched" in data:
        val = data["date_watched"]
        e.date_watched = datetime.fromisoformat(val).date() if val else None
    if "rating" in data:
        e.rating = int(data["rating"]) if data["rating"] not in (
            None, "") else None
    if "review" in data:
        e.review = (data["review"] or "").strip() or None
    db.session.commit()
    return jsonify({"ok": True, "entry": e.to_dict()})


def _norm_title(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.category(c).startswith("M"))
    s = s.lower()
    s = re.sub(r"\(.*?\)", "", s)              # drop parentheticals
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)         # strip punctuation
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _score(title_q: str, title_hit: str, year_q: int | None, year_hit: int | None) -> float:
    """Title similarity + small year bonus (exact=+0.2, off by 1=+0.05)."""
    t = SequenceMatcher(None, _norm_title(title_q),
                        _norm_title(title_hit)).ratio()
    bonus = 0.0
    if year_q and year_hit:
        if year_q == year_hit:
            bonus = 0.20
        elif abs(year_q - year_hit) == 1:
            bonus = 0.05
    return t + bonus


@app.cli.command("backfill-posters")
def backfill_posters():
    filled = 0
    misses = []

    for e in DiaryEntry.query.filter((DiaryEntry.poster_url == None) | (DiaryEntry.poster_url == "")).all():
        # 1) get year hint
        year = e.date_watched.year if e.date_watched else None
        if not year and e.external_id and e.external_id.startswith("letterboxd:"):
            # we sometimes stored title:year in external_id when no URI
            tail = e.external_id.split(":")[-1]
            if tail.isdigit():
                year = int(tail)

        # 2) query the right TMDb endpoint with year
        results = []
        try:
            if e.kind == "movie":
                # /search/movie supports year and primary_release_year
                j = tmdb._get("/search/movie", query=e.title, include_adult=False,
                              year=year, primary_release_year=year or None)
                for it in j.get("results", []):
                    title = it.get("title") or it.get("name")
                    release = (it.get("release_date") or "")[:4]
                    results.append({
                        "id": it.get("id"),
                        "title": title,
                        "year": int(release) if release.isdigit() else None,
                        "poster": tmdb._poster_url(it.get("poster_path"))
                    })
            else:  # series
                j = tmdb._get("/search/tv", query=e.title, include_adult=False,
                              first_air_date_year=year or None)
                for it in j.get("results", []):
                    title = it.get("name") or it.get("title")
                    first = (it.get("first_air_date") or "")[:4]
                    results.append({
                        "id": it.get("id"),
                        "title": title,
                        "year": int(first) if first.isdigit() else None,
                        "poster": tmdb._poster_url(it.get("poster_path"))
                    })
        except Exception:
            results = []

        # 3) pick best match (exact > fuzzy > popularity already implied)
        best = None
        best_score = 0.0
        for r in results:
            score = _score(e.title, r["title"], year, r["year"])
            if _norm_title(r["title"]) == _norm_title(e.title) and (not year or r["year"] == year):
                score += 0.5  # strong boost for exact title (+ year) match
            if score > best_score:
                best, best_score = r, score

        if best and best.get("poster"):
            e.poster_url = best["poster"]
            # Optional: lock in a stable external id when we found a good hit
            # e.external_id = f"tmdb:{best['id']}"
            filled += 1
        else:
            misses.append(f"{e.title} ({year or 'n/a'})")

    db.session.commit()
    print(f"Backfilled posters for {filled} entries.")
    if misses:
        print("No poster found for:")
        for m in misses[:50]:
            print(" -", m)
        if len(misses) > 50:
            print(f" ... and {len(misses)-50} more")


def tmdb_poster_for_movie(title: str, year: int | None):
    # Try with year, then without (handles “watched in 2024, released in 2018”)
    def _search(y):
        try:
            js = tmdb._get("/search/movie", query=title, include_adult=False,
                           year=y or None, primary_release_year=y or None)
            res = js.get("results", [])
        except Exception:
            res = []
        return res

    def _choose(res):
        if not res:
            return None
        # prefer exact title (case/diacritics-insensitive), else first with poster
        import unicodedata
        import re

        def norm(s):
            s = unicodedata.normalize("NFKD", s)
            s = "".join(c for c in s if not unicodedata.category(
                c).startswith("M"))
            s = re.sub(r"\(.*?\)", "", s).lower().strip()
            return s
        ntitle = norm(title)
        exact = next((r for r in res if norm(r.get("title") or r.get(
            "name", "")) == ntitle and r.get("poster_path")), None)
        pick = exact or next((r for r in res if r.get("poster_path")), None)
        if not pick:
            return None
        return f"https://image.tmdb.org/t/p/w500{pick['poster_path']}"

    return _choose(_search(year)) or _choose(_search(None))
