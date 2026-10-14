import os
import sqlite3
import math
from pathlib import Path

from flask import Flask, flash, g, jsonify, redirect, render_template, request, url_for
from restaurant_identity import NEIGHBORHOODS, deduplicate_places, exemplary_source

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "restaurants.db"


def load_local_env():
    """Load simple KEY=value entries from the project .env file, if present."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


load_local_env()
app = Flask(__name__)

SAMPLE_RESTAURANTS = [
    ("중곡동", "샘플 식당 A", "한식", "중곡동 샘플 주소", 127.0830, 37.5650),
    ("군자동", "샘플 식당 B", "분식", "군자동 샘플 주소", 127.0750, 37.5520),
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute("""CREATE TABLE IF NOT EXISTS restaurants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        neighborhood TEXT NOT NULL,
        name TEXT NOT NULL,
        category TEXT,
        business_status TEXT,
        address TEXT,
        longitude REAL,
        latitude REAL,
        source_url TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, address)
    )""")
    columns = {row[1] for row in db.execute("PRAGMA table_info(restaurants)")}
    if "business_status" not in columns:
        db.execute("ALTER TABLE restaurants ADD COLUMN business_status TEXT")
    db.execute("""CREATE TABLE IF NOT EXISTS crawl_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at TEXT,
        status TEXT NOT NULL,
        pages_visited INTEGER NOT NULL DEFAULT 0,
        listings_seen INTEGER NOT NULL DEFAULT 0,
        target_found INTEGER NOT NULL DEFAULT 0,
        inserted INTEGER NOT NULL DEFAULT 0,
        updated INTEGER NOT NULL DEFAULT 0,
        error TEXT
    )""")
    count = db.execute("SELECT COUNT(*) FROM restaurants").fetchone()[0]
    if count == 0:
        db.executemany(
            "INSERT OR IGNORE INTO restaurants "
            "(neighborhood, name, category, address, longitude, latitude) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            SAMPLE_RESTAURANTS,
        )
    db.commit()


def build_filter(neighborhood, query, exemplary_only=False, category=""):
    where_sql = " FROM restaurants WHERE 1=1"
    params = []
    if neighborhood in NEIGHBORHOODS:
        where_sql += " AND neighborhood = ?"
        params.append(neighborhood)
    else:
        where_sql += " AND neighborhood IN (?, ?, ?, ?)"
        params.extend(NEIGHBORHOODS)
    if query:
        where_sql += " AND (name LIKE ? OR category LIKE ? OR address LIKE ?)"
        params.extend([f"%{query}%"] * 3)
    if exemplary_only:
        where_sql += " AND source_url LIKE '%gwangjin.go.kr%'"
    if category:
        where_sql += " AND category = ?"
        params.append(category)
    # Permit CSVs include historical closed and suspended licenses. Keep those
    # out of the current restaurant finder without exposing an uncertain status UI.
    where_sql += " AND (business_status IS NULL OR TRIM(business_status) = '' OR " \
                 "(business_status NOT LIKE '%폐업%' AND business_status NOT LIKE '%휴업%' " \
                 "AND business_status NOT LIKE '%정지%' AND business_status NOT LIKE '%중단%'))"
    real_count = get_db().execute(
        "SELECT COUNT(*) FROM restaurants WHERE NOT "
        "((name = '샘플 식당 A' AND address = '중곡동 샘플 주소') OR "
        "(name = '샘플 식당 B' AND address = '군자동 샘플 주소'))"
    ).fetchone()[0]
    if real_count:
        where_sql += " AND NOT ((name = '샘플 식당 A' AND address = '중곡동 샘플 주소') " \
                     "OR (name = '샘플 식당 B' AND address = '군자동 샘플 주소'))"
    return where_sql, params


@app.route("/")
def index():
    init_db()
    neighborhood = request.args.get("neighborhood", "전체")
    query = request.args.get("q", "").strip()
    exemplary_only = request.args.get("exemplary") == "1"
    category = request.args.get("category", "").strip()
    where_sql, params = build_filter(neighborhood, query, exemplary_only, category)
    db = get_db()
    all_places = deduplicate_places(db.execute(
        "SELECT *" + where_sql + " ORDER BY neighborhood, name", params
    ).fetchall())
    total_count = len(all_places)
    per_page = 30
    total_pages = max(1, math.ceil(total_count / per_page))
    page = max(1, request.args.get("page", 1, type=int))
    page = min(page, total_pages)
    offset = (page - 1) * per_page
    restaurants = all_places[offset:offset + per_page]
    last_crawl = db.execute(
        "SELECT * FROM crawl_runs WHERE status = 'success' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    categories = [row[0] for row in db.execute(
        "SELECT DISTINCT category FROM restaurants WHERE category IS NOT NULL AND TRIM(category) != '' "
        "AND neighborhood IN (?, ?, ?, ?) "
        "AND NOT ((name = '샘플 식당 A' AND address = '중곡동 샘플 주소') "
        "OR (name = '샘플 식당 B' AND address = '군자동 샘플 주소')) "
        "ORDER BY category COLLATE NOCASE",
        NEIGHBORHOODS,
    ).fetchall()]
    return render_template(
        "index.html",
        restaurants=restaurants,
        neighborhood=neighborhood,
        query=query,
        exemplary_only=exemplary_only,
        category=category,
        categories=categories,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        last_crawl=last_crawl,
        map_client_id=os.getenv("NAVER_MAP_CLIENT_ID", ""),
    )


@app.get("/api/restaurants")
def map_restaurants():
    """Return all filtered, located restaurants independently of list pagination."""
    init_db()
    neighborhood = request.args.get("neighborhood", "전체")
    query = request.args.get("q", "").strip()
    exemplary_only = request.args.get("exemplary") == "1"
    category = request.args.get("category", "").strip()
    where_sql, params = build_filter(neighborhood, query, exemplary_only, category)
    rows = get_db().execute(
        "SELECT id, neighborhood, name, category, address, longitude, latitude, source_url"
        + where_sql
        + " AND longitude IS NOT NULL AND latitude IS NOT NULL ORDER BY neighborhood, name",
        params,
    ).fetchall()
    places = deduplicate_places(rows)
    result = []
    for row in places:
        result.append({
            "id": row["id"], "neighborhood": row["neighborhood"],
            "name": row["name"], "category": row["category"],
            "address": row["address"], "longitude": row["longitude"],
            "latitude": row["latitude"], "source_url": row["source_url"],
            "is_exemplary": exemplary_source(row["source_url"]),
        })
    return jsonify(result)


@app.post("/restaurants")
def add_restaurant():
    neighborhood = request.form.get("neighborhood", "").strip()
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    address = request.form.get("address", "").strip()
    source_url = request.form.get("source_url", "").strip()
    try:
        longitude = float(request.form["longitude"]) if request.form.get("longitude", "").strip() else None
        latitude = float(request.form["latitude"]) if request.form.get("latitude", "").strip() else None
    except ValueError:
        flash("경도와 위도는 숫자로 입력해 주세요.", "error")
        return redirect(url_for("index"))

    if neighborhood not in NEIGHBORHOODS or not name:
        flash("동네와 가게 이름을 입력해 주세요.", "error")
        return redirect(url_for("index"))

    init_db()
    try:
        get_db().execute(
            "INSERT INTO restaurants (neighborhood, name, category, address, longitude, latitude, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (neighborhood, name, category, address, longitude, latitude, source_url),
        )
        get_db().commit()
        flash(f"{name}을(를) 저장했어요.", "success")
    except sqlite3.IntegrityError:
        flash("같은 가게 이름과 주소가 이미 등록되어 있어요.", "error")
    return redirect(url_for("index", neighborhood=neighborhood))


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
