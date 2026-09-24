import csv
import io
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template, g, Response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
#DB_PATH = os.path.join(BASE_DIR, 'sensor_data.db')
DB_PATH = "/var/data/sensor_data.db"

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
    cur.execute('CREATE INDEX IF NOT EXISTS idx_history_device_time ON sensor_history(device_name, created_at)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_history_time ON sensor_history(created_at)')
    db.commit()
    db.close()


def now_iso():
    # Render上でも分かりやすいようにタイムゾーン付きISO文字列で保存
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


def as_float(value):
    if value is None or value == '':
        return None
    return float(value)


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

    try:
        temp = as_float(data.get('temp'))
        hum = as_float(data.get('hum'))
        press = as_float(data.get('press'))
        lat = as_float(data.get('lat'))
        lng = as_float(data.get('lng'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'temp/hum/press/lat/lng must be numbers'}), 400

    created_at = now_iso()

    db = get_db()
    db.execute(
        '''
        INSERT INTO sensor_history (device_name, temp, hum, press, lat, lng, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (device_name, temp, hum, press, lat, lng, created_at)
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
        (device_name, temp, hum, press, lat, lng, created_at)
    )
    db.commit()

    return jsonify({'ok': True, 'saved_at': created_at})


@app.route('/api/latest')
def api_latest():
    db = get_db()
    rows = db.execute(
        '''
        SELECT device_name, temp, hum, press, lat, lng, updated_at
        FROM sensor_latest
        ORDER BY device_name
        '''
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route('/api/history')
def api_history():
    device_name = request.args.get('name', '').strip()
    hours = request.args.get('hours', '').strip()
    limit = request.args.get('limit', '500').strip()

    try:
        limit_n = max(1, min(int(limit), 5000))
    except ValueError:
        limit_n = 500

    since = None
    if hours:
        try:
            hours_n = max(1, min(int(hours), 24 * 31))
            since = (datetime.now(timezone.utc).astimezone() - timedelta(hours=hours_n)).isoformat(timespec='seconds')
        except ValueError:
            since = None

    conditions = []
    params = []
    if device_name:
        conditions.append('device_name = ?')
        params.append(device_name)
    if since:
        conditions.append('created_at >= ?')
        params.append(since)

    where_sql = ''
    if conditions:
        where_sql = 'WHERE ' + ' AND '.join(conditions)

    sql = f'''
        SELECT device_name, temp, hum, press, lat, lng, created_at
        FROM sensor_history
        {where_sql}
        ORDER BY created_at ASC
        LIMIT ?
    '''
    params.append(limit_n)

    db = get_db()
    rows = db.execute(sql, params).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route('/download.csv')
def download_csv():
    device_name = request.args.get('name', '').strip()
    limit = request.args.get('limit', '5000').strip()
    try:
        limit_n = max(1, min(int(limit), 50000))
    except ValueError:
        limit_n = 5000

    db = get_db()
    if device_name:
        rows = db.execute(
            '''
            SELECT id, device_name, temp, hum, press, lat, lng, created_at
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
            SELECT id, device_name, temp, hum, press, lat, lng, created_at
            FROM sensor_history
            ORDER BY id DESC
            LIMIT ?
            ''',
            (limit_n,)
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'device_name', 'temp', 'hum', 'press', 'lat', 'lng', 'created_at'])
    for row in rows:
        writer.writerow([row['id'], row['device_name'], row['temp'], row['hum'], row['press'], row['lat'], row['lng'], row['created_at']])

    filename = 'sensor_history.csv' if not device_name else f'sensor_history_{device_name}.csv'
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
else:
    init_db()
