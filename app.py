from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from itertools import groupby
from flask import flash
import os

from tmdb import TMDBClient

app = Flask(__name__)

# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'maximilian.db')}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

db = SQLAlchemy(app)

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
        elif kind == "series":
            item = tmdb.get_series(item_id)
        else:
            return "Unknown kind", 400
        return render_template("item.html", item=item, kind=kind)
    except Exception as e:
        return render_template("item.html", item=None, kind=kind, error=str(e)), 500


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
    added = 0
    errors = 0
    poster_cache = {}

    for row in reader:
        try:
            title = (row.get("Name") or row.get("Title") or "").strip()
            if not title:
                continue
            year = (row.get("Year") or "").strip()
            lb_uri = (row.get("Letterboxd URI") or row.get("Letterboxd URL") or row.get("Letterboxd Uri") or "").strip()
            watched = _parse_lb_date(row.get("Watched Date") or row.get("Date") or "")
            rating = _map_lb_rating(row.get("Rating"))
            tags = (row.get("Tags") or "").strip()
            rewatch = (row.get("Rewatch") or "").strip()
            external_id = f"letterboxd:{lb_uri}" if lb_uri else f"letterboxd:{title}:{year}"

            key = f"{title}|{year}"
            poster = poster_cache.get(key)
            if poster is None:
                try:
                    sr = tmdb.search(f"{title} {year}".strip())
                    poster = sr[0]["poster"] if sr else None
                except Exception:
                    poster = None
                poster_cache[key] = poster

            review_bits = []
            if tags: review_bits.append(f"Tags: {tags}")
            if rewatch.lower().startswith("y"): review_bits.append("Rewatch")
            review = " • ".join(review_bits) if review_bits else None

            db.session.add(DiaryEntry(
                external_id=external_id,
                kind="movie",
                title=title,
                poster_url=poster,
                date_watched=watched,
                rating=rating,
                review=review
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


@app.cli.command("backfill-posters")
def backfill_posters():
    filled = 0
    for e in DiaryEntry.query.filter((DiaryEntry.poster_url == None) | (DiaryEntry.poster_url == "")).all():
        year = e.date_watched.year if e.date_watched else None
        if (not year) and e.external_id.startswith("letterboxd:"):
            parts = e.external_id.split(":")
            if parts and parts[-1].isdigit():
                year = int(parts[-1])
        q = f"{e.title} {year}" if year else e.title
        try:
            r = tmdb.search(q)
            if r and r[0].get("poster"):
                e.poster_url = r[0]["poster"]
                filled += 1
        except Exception:
            pass
    db.session.commit()
    print(f"Backfilled posters for {filled} entries.")