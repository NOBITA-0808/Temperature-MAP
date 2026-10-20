"""Pico classroom sensor/photo map. Run with ONE gunicorn worker (no --preload)."""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import warnings
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import (Flask, abort, g, jsonify, redirect, render_template, request,
                   send_file, session, url_for)
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
DATA_DIR = Path(os.getenv('DATA_DIR', '/var/data' if Path('/var/data').is_dir() else str(BASE_DIR / 'data')))
DB_PATH = Path(os.getenv('DB_PATH', str(DATA_DIR / 'sensor_data.db')))
PHOTO_DIR = DATA_DIR / 'photos'
BACKUP_DIR = DATA_DIR / 'backups'
for folder in (DATA_DIR, DB_PATH.parent, PHOTO_DIR, BACKUP_DIR):
    folder.mkdir(parents=True, exist_ok=True)
LOCK = threading.RLock()
secret = os.getenv('SECRET_KEY', '')
if len(secret) < 32:
    raise RuntimeError('SECRET_KEY を32文字以上のランダムな値で設定してください。READMEを参照。')
app = Flask(__name__, root_path=str(BASE_DIR))
app.config.update(SECRET_KEY=secret, MAX_CONTENT_LENGTH=20 * 1024 * 1024,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', '1') != '0',
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
Image.MAX_IMAGE_PIXELS = 40_000_000
DISPLAY_NAMES = {'pico_test1': '自宅付近', 'pico_test2': '大津駅北口'}
BACKUP_HOURS = float(os.getenv('BACKUP_INTERVAL_HOURS', '24'))
BACKUP_KEEP = max(2, int(os.getenv('BACKUP_KEEP', '7')))
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(20))


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


def backup_snapshot(prefix='backup'):
    """Caller holds LOCK; SQLite online backup + all immutable photo files."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = BACKUP_DIR / f'{prefix}-{stamp}.zip'
    staging_db = BACKUP_DIR / f'.snapshot-{stamp}.db'
    temporary = target.with_suffix('.tmp')
    try:
        with sqlite3.connect(DB_PATH) as source, sqlite3.connect(staging_db) as dest:
            source.backup(dest)
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(staging_db, 'sensor_data.db')
            for photo in sorted(PHOTO_DIR.glob('*.jpg')):
                archive.write(photo, 'photos/' + photo.name)
            archive.writestr('manifest.json', json.dumps({'format': 1, 'created_at': now_iso(),
                                'application': 'sensor_course_v2'}, ensure_ascii=False))
        os.replace(temporary, target)
        if prefix == 'backup':
            for old in sorted(BACKUP_DIR.glob('backup-*.zip'), reverse=True)[BACKUP_KEEP:]:
                old.unlink()
        return target
    finally:
        staging_db.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)


def init_db():
    with LOCK:
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as db:
                cols = [r[1] for r in db.execute('PRAGMA table_info(sensor_history)')]
            if cols and 'deleted_at' not in cols:
                backup_snapshot('before-upgrade')
        with sqlite3.connect(DB_PATH) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sensor_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, device_name TEXT NOT NULL,
                    temp REAL, hum REAL, press REAL, lat REAL, lng REAL, created_at TEXT NOT NULL,
                    deleted_at TEXT);
                CREATE INDEX IF NOT EXISTS idx_history_device_time ON sensor_history(device_name, created_at);
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','member')),
                    active INTEGER NOT NULL DEFAULT 1, auth_version INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS devices (
                    name TEXT PRIMARY KEY, label TEXT NOT NULL, key_hash TEXT NOT NULL,
                    owner_id INTEGER NOT NULL REFERENCES users(id), active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS photos (
                    id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id),
                    filename TEXT NOT NULL, thumbnail TEXT NOT NULL, description TEXT NOT NULL,
                    lat REAL NOT NULL, lng REAL NOT NULL, taken_at TEXT NOT NULL,
                    time_source TEXT NOT NULL, uploaded_at TEXT NOT NULL, deleted_at TEXT);
                CREATE INDEX IF NOT EXISTS idx_photos_date ON photos(taken_at);
                CREATE TABLE IF NOT EXISTS login_attempts (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, started REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, actor TEXT, action TEXT NOT NULL, target TEXT,
                    created_at TEXT NOT NULL);
            ''')
            cols = [r[1] for r in db.execute('PRAGMA table_info(sensor_history)')]
            if 'deleted_at' not in cols:
                db.execute('ALTER TABLE sensor_history ADD COLUMN deleted_at TEXT')
            db.execute('CREATE INDEX IF NOT EXISTS idx_history_jd ON sensor_history(julianday(created_at))')
            db.execute('CREATE INDEX IF NOT EXISTS idx_history_device_jd ON sensor_history(device_name,julianday(created_at))')
            if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                username, password = os.getenv('ADMIN_USERNAME', ''), os.getenv('ADMIN_PASSWORD', '')
                if username and password:
                    validate_username(username)
                    validate_password(password)
                    db.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',
                               (username, generate_password_hash(password), 'admin'))


def validate_username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', value):
        raise ValueError('IDは英数字・_・.・-の3〜40文字にしてください。')
    return value


def validate_password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 128:
        raise ValueError('パスワードは12〜128文字にしてください。')
    return value


def audit(action, target):
    get_db().execute('INSERT INTO audit(actor,action,target,created_at) VALUES(?,?,?,?)',
                    (g.user['username'] if g.user else None, action, str(target), now_iso()))


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def protect():
    # A single process lock keeps photo writes and backup snapshots consistent.
    LOCK.acquire()
    g.held_lock = True
    g.user = None
    uid = session.get('uid')
    if uid:
        user = get_db().execute('SELECT * FROM users WHERE id=? AND active=1', (uid,)).fetchone()
        if user and user['auth_version'] == session.get('version'):
            g.user = user
        else:
            session.clear()
    if request.endpoint in ('health', 'static'):
        return
    if request.endpoint not in ('login', 'save_sensor_data') and not g.user:
        if request.path.startswith('/api/') or request.endpoint in ('api_latest', 'api_history', 'compare', 'download_csv', 'photo_file'):
            abort(401, 'ログインが必要です。')
        return redirect(url_for('login'))
    if request.endpoint and request.endpoint.startswith('admin_') and (not g.user or g.user['role'] != 'admin'):
        abort(403, '管理者のみ操作できます。')
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.endpoint != 'save_sensor_data':
        token = request.headers.get('X-CSRF-Token') or request.form.get('csrf', '')
        if not token or not hmac.compare_digest(token, session.get('csrf', '')):
            abort(400, '画面を再読込してから操作してください（CSRF確認）。')


@app.after_request
def response_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.endpoint not in ('static', 'health'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.teardown_request
def release(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()
    if g.pop('held_lock', False):
        LOCK.release()


@app.errorhandler(HTTPException)
def http_error(exc):
    if request.path.startswith('/api') or request.is_json:
        return jsonify(ok=False, error=exc.description), exc.code
    return render_template('message.html', message=exc.description), exc.code


@app.errorhandler(ValueError)
def invalid(exc):
    return http_error(HTTPExceptionWithMessage(str(exc), 400))


class HTTPExceptionWithMessage(HTTPException):
    def __init__(self, message, code):
        self.code = code
        super().__init__(description=message)


@app.route('/health')
def health():
    return {'status': 'ok'}


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')[:128]
        # Per-account bucket also limits attempts across IP addresses; stored in SQLite across restarts.
        bucket = hashlib.sha256(username.casefold().encode()).hexdigest()
        db = get_db()
        db.execute('DELETE FROM login_attempts WHERE started < ?', (time.time() - 900,))
        attempt = db.execute('SELECT * FROM login_attempts WHERE bucket=?', (bucket,)).fetchone()
        if attempt and attempt['count'] >= 10:
            db.commit()
            abort(429, '試行回数が多いため15分ほど待ってください。')
        user = db.execute('SELECT * FROM users WHERE username=? AND active=1', (username,)).fetchone()
        password = request.form.get('password', '')[:129]
        valid = check_password_hash(user['password_hash'] if user else DUMMY_HASH, password)
        if user and valid:
            db.execute('DELETE FROM login_attempts WHERE bucket=?', (bucket,))
            db.commit()
            session.clear()
            session.update(uid=user['id'], version=user['auth_version'])
            session.permanent = True
            return redirect(url_for('index'))
        db.execute('''INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(bucket)
                      DO UPDATE SET count=count+1''', (bucket, time.time()))
        db.commit()
        error = 'IDまたはパスワードが違います。'
    return render_template('login.html', error=error)


@app.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/password', methods=['GET', 'POST'])
def password():
    if request.method == 'POST':
        if not check_password_hash(g.user['password_hash'], request.form.get('current', '')):
            abort(400, '現在のパスワードが違います。')
        new = validate_password(request.form.get('password', ''))
        if new != request.form.get('confirm'):
            abort(400, '新しいパスワードが一致しません。')
        db = get_db()
        db.execute('UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE id=?',
                   (generate_password_hash(new), g.user['id']))
        audit('password_change', g.user['id'])
        db.commit()
        session['version'] = g.user['auth_version'] + 1
        return render_template('message.html', message='パスワードを変更しました。')
    return render_template('password.html')


@app.get('/')
def index():
    return render_template('map.html')


def as_float(value, low=None, high=None):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('数値を入力してください。')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("数値を入力してください。") from None
    if not math.isfinite(value) or (low is not None and value < low) or (high is not None and value > high):
        raise ValueError('数値が有効範囲外です。')
    return value


def json_data():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, 'JSONオブジェクトを送信してください。')
    return data


@app.post('/api')
def save_sensor_data():
    data = json_data()
    name = data.get('name')
    if not isinstance(name, str) or not 1 <= len(name) <= 80:
        abort(400, 'nameを指定してください。')
    authorization = request.headers.get('Authorization', '')
    key = authorization[7:] if authorization.startswith('Bearer ') else ''
    device = get_db().execute('''SELECT d.* FROM devices d JOIN users u ON u.id=d.owner_id
                                WHERE d.name=? AND d.active=1 AND u.active=1''', (name,)).fetchone()
    candidate = hashlib.sha256(key.encode()).hexdigest()
    expected = device['key_hash'] if device else '0' * 64
    if not key or not hmac.compare_digest(candidate, expected) or not device:
        abort(401, '機器名または送信用キーが無効です。')
    temp = as_float(data.get('temp'), -100, 100)
    hum = as_float(data.get('hum'), 0, 100)
    press = as_float(data.get('press', data.get('pres')), 0, 1200)
    lat, lng = as_float(data.get('lat'), -90, 90), as_float(data.get('lng'), -180, 180)
    if all(v is None for v in (temp, hum, press)):
        abort(400, '観測値を1つ以上指定してください。')
    if (lat is None) != (lng is None):
        abort(400, '緯度と経度は両方指定してください。')
    stamp = now_iso()
    db = get_db()
    db.execute('''INSERT INTO sensor_history(device_name,temp,hum,press,lat,lng,created_at)
                  VALUES(?,?,?,?,?,?,?)''', (name, temp, hum, press, lat, lng, stamp))
    db.commit()
    return jsonify(ok=True, saved_at=stamp, display_name=device['label'])


def display_name_for(name):
    row = get_db().execute('SELECT label FROM devices WHERE name=?', (name,)).fetchone()
    return row['label'] if row else DISPLAY_NAMES.get(name, name)


def to_view(row):
    result = dict(row)
    result.update(name=row['device_name'], display_name=display_name_for(row['device_name']),
                  recorded_at=row['created_at'], updated_at=row['created_at'])
    return result


def time_bounds():
    day = request.args.get('date', '')
    if day:
        start = datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=JST)
        return start.isoformat(), (start + timedelta(days=1)).isoformat()
    hours = max(1, min(168, int(request.args.get('hours', '24'))))
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    return (end - timedelta(hours=hours)).isoformat(), end.isoformat()


def observations(device=None, all_time=False):
    sql, params = 'SELECT * FROM sensor_history WHERE deleted_at IS NULL', []
    if device:
        sql += ' AND device_name=?'
        params.append(device)
    if not all_time:
        start, end = time_bounds()
        sql += ' AND julianday(created_at)>=julianday(?) AND julianday(created_at)<julianday(?)'
        params.extend([start, end])
    sql += ' ORDER BY julianday(created_at),id'
    return get_db().execute(sql, params).fetchall()


def latest_rows():
    where = 'deleted_at IS NULL'
    params = []
    if request.args.get('date'):
        start, end = time_bounds()
        where += ' AND julianday(created_at)>=julianday(?) AND julianday(created_at)<julianday(?)'
        params = [start, end]
    sql = f"""SELECT * FROM (
        SELECT *, ROW_NUMBER() OVER(PARTITION BY device_name
        ORDER BY julianday(created_at) DESC,id DESC) AS rank FROM sensor_history WHERE {where}
        ) WHERE rank=1 ORDER BY device_name"""
    return [to_view(r) for r in get_db().execute(sql, params)]


@app.get('/latest')
@app.get('/api/latest')
@app.get('/data')
def api_latest():
    return jsonify(latest_rows())


@app.get('/history')
@app.get('/api/history')
def api_history():
    name = request.args.get('name', '').strip()
    if not name:
        abort(400, 'nameを指定してください。')
    return jsonify([to_view(r) for r in observations(name)])


@app.get('/compare')
def compare():
    names = [v for v in request.args.get('names', '').split(',') if v]
    series = {}
    for row in observations():
        name = row['device_name']
        if names and name not in names:
            continue
        series.setdefault(name, dict(name=name, display_name=display_name_for(name), points=[]))['points'].append(
            dict(recorded_at=row['created_at'], temp=row['temp']))
    return jsonify(list(series.values()))


@app.get('/csv')
@app.get('/download.csv')
def download_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id','device_id','display_name','temp','hum','press','lat','lng','recorded_at'])
    for row in observations(all_time=not bool(request.args.get('date'))):
        name = display_name_for(row['device_name'])
        # Neutralize spreadsheet formulas in user-defined labels.
        safe = lambda v: "'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v
        writer.writerow([row['id'], safe(row['device_name']), safe(name), row['temp'], row['hum'], row['press'], row['lat'], row['lng'], row['created_at']])
    return app.response_class('\ufeff' + output.getvalue(), mimetype='text/csv',
                              headers={'Content-Disposition': 'attachment; filename=sensor_data.csv'})


def parse_taken(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds')


def photo_metadata(image):
    exif = image.getexif()
    extra = exif.get_ifd(34665) if 34665 in exif else {}
    gps = exif.get_ifd(34853) if 34853 in exif else {}
    lat = lng = taken = None
    source = '未指定'
    try:
        def degrees(parts):
            return float(parts[0]) + float(parts[1])/60 + float(parts[2])/3600
        if 2 in gps and 4 in gps:
            lat, lng = degrees(gps[2]), degrees(gps[4])
            if gps.get(1) in ('S', b'S'):
                lat = -lat
            if gps.get(3) in ('W', b'W'):
                lng = -lng
            as_float(lat, -90, 90)
            as_float(lng, -180, 180)
    except (ValueError, TypeError, IndexError, ZeroDivisionError, OverflowError):
        lat = lng = None
    try:
        raw = extra.get(36867) or exif.get(306)
        if raw:
            dt = datetime.strptime(str(raw).strip('\x00'), '%Y:%m:%d %H:%M:%S')
            offset = extra.get(36881) or extra.get(36880)
            taken = parse_taken(dt.isoformat() + str(offset).strip('\x00') if offset else dt.isoformat())
            source = 'EXIF' if offset else 'EXIF（時差なしのため日本時間として読取）'
    except (ValueError, TypeError):
        pass
    return dict(lat=lat, lng=lng, taken_at=taken, time_source=source)


def read_photo():
    upload = request.files.get('photo')
    if not upload:
        abort(400, '写真を選択してください。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            image = Image.open(upload.stream)
            if image.format not in ('JPEG', 'PNG', 'WEBP', 'HEIF', 'AVIF'):
                abort(400, 'JPEG・PNG・WebP・HEIC形式を選んでください。')
            meta = photo_metadata(image)
            image.load()
            image = ImageOps.exif_transpose(image)
            # Re-encode, stripping all EXIF (GPS retained only in access-controlled database).
            if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
                rgba = image.convert('RGBA')
                rgb = Image.new('RGB', rgba.size, 'white')
                rgb.paste(rgba, mask=rgba.getchannel('A'))
                image = rgb
            else:
                image = image.convert('RGB')
            image.thumbnail((1600, 1600))
            return image, meta
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning, ValueError, TypeError) as exc:
        abort(400, '写真を読み取れません。画像形式・サイズをご確認ください。')


@app.post('/api/photos/metadata')
def metadata():
    image, meta = read_photo()
    image.close()
    return jsonify(meta)


def photo_fields(meta=None):
    meta = meta or {}
    lat = as_float(request.form.get('lat') or meta.get('lat'), -90, 90)
    lng = as_float(request.form.get('lng') or meta.get('lng'), -180, 180)
    if lat is None or lng is None:
        abort(400, 'GPS情報がない写真は地図をクリックして場所を指定してください。')
    explicit = request.form.get('taken_at', '')
    taken = parse_taken(explicit) if explicit else meta.get('taken_at')
    if not taken:
        abort(400, '撮影日時を指定してください。')
    description = request.form.get('description', '').strip()
    if len(description) > 1000:
        abort(400, '説明は1000文字以内にしてください。')
    return lat, lng, taken, description


@app.post('/api/photos')
def upload_photo():
    image, meta = read_photo()
    lat, lng, taken, description = photo_fields(meta)
    image_bytes, thumb_bytes = io.BytesIO(), io.BytesIO()
    image.save(image_bytes, format='JPEG', quality=85)
    thumb = ImageOps.fit(image, (96, 96))
    thumb.save(thumb_bytes, format='JPEG', quality=80)
    image.close()
    total = sum(p.stat().st_size for p in PHOTO_DIR.glob('*.jpg'))
    required = len(image_bytes.getvalue()) + len(thumb_bytes.getvalue())
    quota = int(os.getenv('MAX_PHOTO_STORAGE_MB', '500')) * 1024**2
    reserve = int(os.getenv('MIN_FREE_DISK_MB', '100')) * 1024**2
    if total + required > quota or shutil.disk_usage(DATA_DIR).free < required + reserve:
        abort(413, '写真の保存容量が不足しています。管理者にご連絡ください。')
    stem = secrets.token_hex(16)
    filename, thumbnail = f'{stem}.jpg', f'{stem}-thumb.jpg'
    db = get_db()
    try:
        (PHOTO_DIR / filename).write_bytes(image_bytes.getvalue())
        (PHOTO_DIR / thumbnail).write_bytes(thumb_bytes.getvalue())
        cur = db.execute('''INSERT INTO photos(owner_id,filename,thumbnail,description,lat,lng,taken_at,time_source,uploaded_at)
                            VALUES(?,?,?,?,?,?,?,?,?)''',
                         (g.user['id'], filename, thumbnail, description, lat, lng, taken,
                          '入力・確認済み（日本時間）' if request.form.get('taken_at') else meta['time_source'], now_iso()))
        audit('photo_upload', cur.lastrowid)
        db.commit()
    except Exception:
        db.rollback()
        (PHOTO_DIR / filename).unlink(missing_ok=True)
        (PHOTO_DIR / thumbnail).unlink(missing_ok=True)
        raise
    return jsonify(ok=True, id=cur.lastrowid), 201


def photo_view(row):
    return dict(id=row['id'], owner_id=row['owner_id'], username=row['username'],
                description=row['description'], lat=row['lat'], lng=row['lng'], taken_at=row['taken_at'],
                time_source=row['time_source'], can_edit=g.user['role']=='admin' or g.user['id']==row['owner_id'],
                url=url_for('photo_file', photo_id=row['id'], kind='full'),
                thumbnail_url=url_for('photo_file', photo_id=row['id'], kind='thumb'))


@app.get('/api/photos')
def list_photos():
    offset = max(0, int(request.args.get('offset', '0')))
    sql = 'SELECT p.*,u.username FROM photos p JOIN users u ON u.id=p.owner_id WHERE p.deleted_at IS NULL'
    params = []
    if request.args.get('date'):
        start, end = time_bounds()
        sql += ' AND julianday(p.taken_at)>=julianday(?) AND julianday(p.taken_at)<julianday(?)'
        params.extend([start, end])
    rows = get_db().execute(sql + ' ORDER BY p.id DESC LIMIT 201 OFFSET ?', params+[offset]).fetchall()
    return jsonify(items=[photo_view(r) for r in rows[:200]], next_offset=offset+200 if len(rows)>200 else None)


def photo_row(photo_id, include_deleted=False):
    row = get_db().execute('SELECT p.*,u.username FROM photos p JOIN users u ON u.id=p.owner_id WHERE p.id=?', (photo_id,)).fetchone()
    if not row or (row['deleted_at'] and not include_deleted):
        abort(404, '写真が見つかりません。')
    return row


def haversine(lat1,lng1,lat2,lng2):
    a,b = math.radians(lat1),math.radians(lat2)
    d = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lng2-lng1)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(d)))


@app.get('/api/photos/<int:photo_id>')
def photo_detail(photo_id):
    row = photo_row(photo_id)
    result = photo_view(row)
    # No current or distant readings are silently represented as weather at the photo.
    rows = get_db().execute('''SELECT * FROM sensor_history WHERE deleted_at IS NULL
        AND ABS((julianday(created_at)-julianday(?))*1440)<=60 AND lat IS NOT NULL AND lng IS NOT NULL''', (row['taken_at'],)).fetchall()
    choices = []
    for obs in rows:
        distance = haversine(row['lat'],row['lng'],obs['lat'],obs['lng'])
        if distance <= 5000:
            delta = abs((datetime.fromisoformat(obs['created_at'].replace('Z','+00:00')) - datetime.fromisoformat(row['taken_at'])).total_seconds())/60
            choices.append((distance,delta,obs))
    result['observation'] = None
    if choices:
        distance, delta, obs = min(choices, key=lambda x:(x[0],x[1]))
        result['observation'] = dict(**to_view(obs), distance_m=round(distance), time_diff_minutes=round(delta,1))
    return jsonify(result)


@app.get('/photos/<int:photo_id>/<kind>')
def photo_file(photo_id, kind):
    if kind not in ('full','thumb'):
        abort(404)
    row = photo_row(photo_id, include_deleted=g.user['role']=='admin')
    return send_file(PHOTO_DIR / row['filename' if kind=='full' else 'thumbnail'], mimetype='image/jpeg')


@app.post('/api/photos/<int:photo_id>/edit')
def edit_photo(photo_id):
    row = photo_row(photo_id)
    if g.user['role'] != 'admin' and row['owner_id'] != g.user['id']:
        abort(403, '自分の写真だけ編集できます。')
    lat, lng, taken, description = photo_fields()
    db = get_db()
    db.execute('UPDATE photos SET lat=?,lng=?,taken_at=?,description=?,time_source=? WHERE id=?',
               (lat,lng,taken,description,'入力・確認済み（日本時間）',photo_id))
    audit('photo_edit', photo_id)
    db.commit()
    return jsonify(ok=True)


@app.get('/admin')
def admin_page():
    db = get_db()
    return render_template('admin.html', users=db.execute('SELECT id,username,role,active FROM users ORDER BY id').fetchall(),
        devices=db.execute('SELECT d.name,d.label,d.owner_id,d.active,u.username FROM devices d JOIN users u ON u.id=d.owner_id ORDER BY d.name').fetchall(),
        photos=db.execute('SELECT id,description,deleted_at FROM photos WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT 100').fetchall(),
        sensors=db.execute('SELECT id,device_name,created_at,deleted_at FROM sensor_history WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT 100').fetchall(),
        backups=sorted([p.name for p in BACKUP_DIR.glob('*.zip')], reverse=True),
        usage_mb=round(sum(p.stat().st_size for p in PHOTO_DIR.glob('*.jpg'))/1024**2,1),
        free_mb=round(shutil.disk_usage(DATA_DIR).free/1024**2),
        observations=db.execute('SELECT id,device_name,temp,created_at FROM sensor_history WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 100').fetchall())


@app.post('/admin/users')
def admin_users():
    username = validate_username(request.form.get('username',''))
    password = validate_password(request.form.get('password',''))
    db = get_db()
    try:
        db.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)', (username,generate_password_hash(password),'member'))
        audit('user_create',username)
        db.commit()
    except sqlite3.IntegrityError:
        abort(409,'そのIDは既に登録されています。')
    return redirect(url_for('admin_page'))


@app.post('/admin/users/<int:uid>/<action>')
def admin_user_action(uid, action):
    if uid == g.user['id']:
        abort(400,'自分の変更はパスワード変更画面を使ってください。')
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=? AND role='member'",(uid,)).fetchone()
    if not user:
        abort(404)
    if action == 'toggle':
        db.execute('UPDATE users SET active=1-active,auth_version=auth_version+1 WHERE id=?',(uid,))
    elif action == 'reset':
        password = validate_password(request.form.get('password',''))
        db.execute('UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE id=?',(generate_password_hash(password),uid))
    else:
        abort(404)
    audit('user_'+action,uid)
    db.commit()
    return redirect(url_for('admin_page'))


@app.post('/admin/devices')
def admin_devices():
    name = request.form.get('name','')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', name):
        abort(400,'機器名は英数字・_・.・-の1〜80文字にしてください。')
    label = request.form.get('label','').strip() or name
    if len(label)>80:
        abort(400,'表示名は80文字以内です。')
    owner = int(request.form.get('owner_id','0'))
    db = get_db()
    if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(owner,)).fetchone():
        abort(400,'有効な所有者を選んでください。')
    key = secrets.token_urlsafe(32)
    try:
        db.execute('INSERT INTO devices(name,label,key_hash,owner_id) VALUES(?,?,?,?)',
                   (name,label,hashlib.sha256(key.encode()).hexdigest(),owner))
        audit('device_create',name)
        db.commit()
    except sqlite3.IntegrityError:
        abort(409,'機器名が重複しています。再発行は既存機器のボタンから行ってください。')
    return render_template('key.html', name=name, key=key)


@app.post('/admin/devices/<name>/<action>')
def admin_device_action(name, action):
    db = get_db()
    device = db.execute('SELECT * FROM devices WHERE name=?',(name,)).fetchone()
    if not device:
        abort(404)
    key = None
    if action == 'rotate':
        key = secrets.token_urlsafe(32)
        db.execute('UPDATE devices SET key_hash=? WHERE name=?',(hashlib.sha256(key.encode()).hexdigest(),name))
    elif action == 'toggle':
        db.execute('UPDATE devices SET active=1-active WHERE name=?',(name,))
    else:
        abort(404)
    audit('device_'+action,name)
    db.commit()
    if key:
        return render_template('key.html',name=name,key=key)
    return redirect(url_for('admin_page'))


@app.post('/admin/<kind>/<int:item_id>/<action>')
def admin_trash(kind,item_id,action):
    tables = {'photos':'photos','observations':'sensor_history'}
    if kind not in tables or action not in ('trash','restore'):
        abort(404)
    if request.form.get('confirm') != 'yes':
        abort(400,'確認後に操作してください。')
    table = tables[kind]
    db = get_db()
    if not db.execute(f'SELECT 1 FROM {table} WHERE id=?',(item_id,)).fetchone():
        abort(404)
    db.execute(f'UPDATE {table} SET deleted_at=? WHERE id=?',(now_iso() if action=='trash' else None,item_id))
    audit(kind+'_'+action,item_id)
    db.commit()
    if request.headers.get('X-CSRF-Token'):
        return jsonify(ok=True)
    return redirect(url_for('admin_page'))


@app.post('/admin/backups')
def admin_backup():
    path = backup_snapshot()
    return render_template('message.html',message=f'バックアップを作成しました：{path.name}')


@app.get('/admin/backups/<name>')
def admin_backup_download(name):
    if not re.fullmatch(r'(backup|before-upgrade)-[0-9TZ]+\.zip',name):
        abort(404)
    path = BACKUP_DIR/name
    if not path.is_file():
        abort(404)
    return send_file(path,as_attachment=True,download_name=name)


def backup_loop():
    while True:
        try:
            with LOCK:
                backups = list(BACKUP_DIR.glob('backup-*.zip'))
                newest = max((p.stat().st_mtime for p in backups),default=0)
                if time.time()-newest >= BACKUP_HOURS*3600:
                    backup_snapshot()
        except Exception:
            app.logger.exception('Automatic backup failed; check disk space and download an external backup.')
        time.sleep(60)


init_db()
if BACKUP_HOURS > 0:
    threading.Thread(target=backup_loop,name='daily-backup',daemon=True).start()

if __name__ == '__main__':
    app.run(host='127.0.0.1',port=int(os.getenv('PORT','5000')),debug=False)
