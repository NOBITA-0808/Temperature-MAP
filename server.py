import os
import sqlite3
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'sensor_data.db')

app = Flask(__name__)


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute(
        '''
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
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS sensor_latest (
            device_name TEXT PRIMARY KEY,
            temp REAL,
            hum REAL,
            press REAL,
            lat REAL,
            lng REAL,
            updated_at TEXT NOT NULL
        )
        '''
    )
    db.commit()
    db.close()


def utc_now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


@app.route('/')
def index():
    return render_template('map.html')


@app.route('/health')
def health():
    return {'status': 'ok'}


@app.route('/api', methods=['POST'])
def save_sensor_data():
    data = request.get_json(silent=True) or {}

    device_name = str(data.get('name', '')).strip()
    if not device_name:
        return jsonify({'ok': False, 'error': 'name is required'}), 400

    temp = data.get('temp')
    hum = data.get('hum')
    press = data.get('press')
    lat = data.get('lat')
    lng = data.get('lng')
    now = utc_now_iso()

    db = get_db()
    db.execute(
        '''
        INSERT INTO sensor_history (device_name, temp, hum, press, lat, lng, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (device_name, temp, hum, press, lat, lng, now)
    )
    db.execute(
        '''
        INSERT INTO sensor_latest (device_name, temp, hum, press, lat, lng, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_name) DO UPDATE SET
            temp = excluded.temp,
            hum = excluded.hum,
            press = excluded.press,
            lat = excluded.lat,
            lng = excluded.lng,
            updated_at = excluded.updated_at
        ''',
        (device_name, temp, hum, press, lat, lng, now)
    )
    db.commit()

    return jsonify({'ok': True, 'saved_at': now})


@app.route('/api/latest')
def api_latest():
    db = get_db()
    rows = db.execute(
        'SELECT device_name, temp, hum, press, lat, lng, updated_at FROM sensor_latest ORDER BY device_name'
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route('/api/history')
def api_history():
    device_name = request.args.get('name', '').strip()
    limit = request.args.get('limit', '100').strip()
    try:
        limit_n = max(1, min(int(limit), 1000))
    except ValueError:
        limit_n = 100

    db = get_db()
    if device_name:
        rows = db.execute(
            '''
            SELECT device_name, temp, hum, press, lat, lng, created_at
            FROM sensor_history
            WHERE device_name = ?
            ORDER BY id DESC
            LIMIT ?
            ''',
            (device_name, limit_n)
        ).fetchall()
    else:
        rows = db.execute(
            '''
            SELECT device_name, temp, hum, press, lat, lng, created_at
            FROM sensor_history
            ORDER BY id DESC
            LIMIT ?
            ''',
            (limit_n,)
        ).fetchall()
    return jsonify([dict(row) for row in rows])


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
else:
    init_db()
