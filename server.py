from __future__ import annotations

import csv
import io
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, Response, g, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parent
DISPLAY_NAMES = {
    "pico_test1": "自宅付近",
    "pico_test2": "大津駅北口",
}


def resolve_db_path() -> Path:
    env = os.environ.get("DB_PATH")
    if env:
        return Path(env)
    if Path("/var/data").is_dir():
        return Path("/var/data/sensor_data.db")
    return BASE_DIR / "sensor_data.db"


DB_PATH = resolve_db_path()
app = Flask(__name__)


def display_name_for(device_id: str) -> str:
    return DISPLAY_NAMES.get(device_id, device_id)


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
        g.db = connection
    return g.db


@app.teardown_appcontext
def close_db(exception=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            temp REAL,
            hum REAL,
            press REAL,
            lat REAL,
            lng REAL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_latest (
            device_name TEXT PRIMARY KEY,
            temp REAL,
            hum REAL,
            press REAL,
            lat REAL,
            lng REAL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_device_time "
        "ON sensor_history(device_name, created_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_time ON sensor_history(created_at)"
    )
    db.commit()
    db.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def as_float(value):
    if value is None or value == "":
        return None
    return float(value)


def to_view(device_id, temp, hum, press, lat, lng, recorded_at) -> dict:
    label = display_name_for(device_id)
    return {
        "name": device_id,
        "device_name": device_id,
        "display_name": label,
        "temp": temp,
        "hum": hum,
        "press": press,
        "lat": lat,
        "lng": lng,
        "recorded_at": recorded_at,
        "updated_at": recorded_at,
        "created_at": recorded_at,
    }


@app.route("/")
def index():
    return render_template("map.html")


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/api", methods=["POST"])
def save_sensor_data():
    data = request.get_json(silent=True) or {}

    device_name = str(data.get("name", "")).strip()
    if not device_name:
        return jsonify({"ok": False, "error": "name is required"}), 400

    try:
        temp = as_float(data.get("temp"))
        hum = as_float(data.get("hum"))
        raw_press = data.get("press", data.get("pres"))
        press = as_float(raw_press)
        lat = as_float(data.get("lat"))
        lng = as_float(data.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "temp/hum/press/lat/lng must be numbers"}), 400

    created_at = now_iso()
    db = get_db()
    db.execute(
        """
        INSERT INTO sensor_history (device_name, temp, hum, press, lat, lng, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (device_name, temp, hum, press, lat, lng, created_at),
    )
    db.execute(
        """
        INSERT INTO sensor_latest (device_name, temp, hum, press, lat, lng, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_name) DO UPDATE SET
            temp = excluded.temp,
            hum = excluded.hum,
            press = excluded.press,
            lat = excluded.lat,
            lng = excluded.lng,
            updated_at = excluded.updated_at
        """,
        (device_name, temp, hum, press, lat, lng, created_at),
    )
    db.commit()
    return jsonify({"ok": True, "saved_at": created_at, "display_name": display_name_for(device_name)})


def latest_rows() -> list[dict]:
    rows = get_db().execute(
        """
        SELECT device_name, temp, hum, press, lat, lng, updated_at
        FROM sensor_latest
        ORDER BY device_name
        """
    ).fetchall()
    return [
        to_view(
            row["device_name"],
            row["temp"],
            row["hum"],
            row["press"],
            row["lat"],
            row["lng"],
            row["updated_at"],
        )
        for row in rows
    ]


@app.route("/api/latest")
@app.route("/latest")
@app.route("/data")
def api_latest():
    return jsonify(latest_rows())


def history_rows(device_name: str, hours: int) -> list[dict]:
    since = (datetime.now(timezone.utc).astimezone() - timedelta(hours=hours)).isoformat(
        timespec="seconds"
    )
    rows = get_db().execute(
        """
        SELECT device_name, temp, hum, press, lat, lng, created_at
        FROM sensor_history
        WHERE device_name = ? AND created_at >= ?
        ORDER BY created_at ASC, id ASC
        """,
        (device_name, since),
    ).fetchall()
    return [
        to_view(
            row["device_name"],
            row["temp"],
            row["hum"],
            row["press"],
            row["lat"],
            row["lng"],
            row["created_at"],
        )
        for row in rows
    ]


@app.route("/api/history")
@app.route("/history")
def api_history():
    device_name = request.args.get("name", "").strip()
    if not device_name:
        return jsonify({"error": "name を指定してください"}), 400

    try:
        hours = min(max(int(request.args.get("hours", 24)), 1), 168)
    except ValueError:
        hours = 24

    return jsonify(history_rows(device_name, hours))


@app.route("/compare")
def compare():
    try:
        hours = min(max(int(request.args.get("hours", 24)), 1), 168)
    except ValueError:
        hours = 24

    requested = [name.strip() for name in request.args.get("names", "").split(",")]
    requested = [name for name in requested if name]
    since = (datetime.now(timezone.utc).astimezone() - timedelta(hours=hours)).isoformat(
        timespec="seconds"
    )

    sql = """
        SELECT device_name, temp, created_at
        FROM sensor_history
        WHERE created_at >= ?
    """
    params: list[object] = [since]
    if requested:
        placeholders = ",".join("?" for _ in requested)
        sql += f" AND device_name IN ({placeholders})"
        params.extend(requested)
    sql += " ORDER BY device_name ASC, created_at ASC, id ASC"

    rows = get_db().execute(sql, params).fetchall()
    series: dict[str, dict] = {}
    for row in rows:
        item = series.setdefault(
            row["device_name"],
            {
                "name": row["device_name"],
                "display_name": display_name_for(row["device_name"]),
                "points": [],
            },
        )
        item["points"].append({"recorded_at": row["created_at"], "temp": row["temp"]})

    return jsonify(list(series.values()))


def build_csv() -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["device_id", "display_name", "temp", "hum", "press", "lat", "lng", "recorded_at"]
    )
    rows = get_db().execute(
        """
        SELECT device_name, temp, hum, press, lat, lng, created_at
        FROM sensor_history
        ORDER BY created_at ASC, id ASC
        """
    ).fetchall()
    for row in rows:
        writer.writerow(
            [
                row["device_name"],
                display_name_for(row["device_name"]),
                row["temp"],
                row["hum"],
                row["press"],
                row["lat"],
                row["lng"],
                row["created_at"],
            ]
        )
    return output.getvalue()


@app.route("/csv")
@app.route("/download.csv")
def download_csv():
    return Response(
        build_csv(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=sensor_data.csv"},
    )


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
