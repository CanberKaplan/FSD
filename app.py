import os
import time
import hmac
import uuid
import json
import pickle
import base64
import hashlib
import secrets
from datetime import timedelta
from flask import Flask, request, jsonify, send_from_directory, session, redirect, Response
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

import sys
# Windows konsolu (cp1252) Türkçe karakterli print'lerde çökmesin
for _stream in (sys.stdout, sys.stderr):
    try:
        # line_buffering: loglar (Render dahil) tamponda beklemeden hemen görünsün
        _stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass

app = Flask(__name__, static_folder='public')

# ── GİRİŞ (ŞİFRE) KORUMASI ───────────────────────────────────────────────────
# APP_PASSWORD : giriş şifresi (Render → Environment). Tanımlı değilse
#                uygulama kilitli kalır, kimse giremez.
# SECRET_KEY   : oturum çerezini imzalayan anahtar. Tanımlı değilse her
#                yeniden başlatmada rastgele üretilir (herkes tekrar giriş yapar).
APP_PASSWORD = os.getenv('APP_PASSWORD', '')
app.secret_key = os.getenv('SECRET_KEY') or secrets.token_hex(32)
if not os.getenv('SECRET_KEY'):
    print("UYARI: SECRET_KEY tanımlı değil, geçici anahtar kullanılıyor.")
if not APP_PASSWORD:
    print("UYARI: APP_PASSWORD tanımlı değil, uygulamaya giriş yapılamaz.")
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=365),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=bool(os.getenv('RENDER')),  # Render'da yalnızca HTTPS
)

# Şifre değişince eski oturumlar otomatik geçersiz olsun
_PW_FINGERPRINT = hashlib.sha256(('fsd:' + APP_PASSWORD).encode()).hexdigest()[:16]

# Giriş sayfasının kendisi için gereken, şifresiz erişilebilen dosyalar
PUBLIC_PATHS = {'/login', '/logout', '/sw.js', '/manifest.json', '/favicon-32.png',
                '/apple-touch-icon.png', '/icon-192.png', '/icon-512.png',
                '/logo_son.png', '/logo_son.svg'}

# Kaba kuvvet denemelerine karşı basit sınır (15 dakikalık pencere):
# IP başına 5 hatalı deneme, ayrıca IP'den bağımsız toplam 30 hatalı deneme.
# X-Forwarded-For başlığı sahte gönderilebildiği için toplam sınır asıl
# korumadır; açık oturumlar (çerezli cihazlar) bu kilitten etkilenmez.
_MAX_FAILS, _MAX_FAILS_GLOBAL, _WINDOW = 5, 30, 15 * 60
_GLOBAL = '*'
_failed_logins = {}

def _client_ip():
    fwd = request.headers.get('X-Forwarded-For', '')
    return fwd.split(',')[0].strip() if fwd else (request.remote_addr or '?')

def _recent_fails(key):
    now = time.time()
    attempts = [t for t in _failed_logins.get(key, []) if now - t < _WINDOW]
    _failed_logins[key] = attempts
    return len(attempts)

def _is_locked_out(ip):
    return _recent_fails(ip) >= _MAX_FAILS or _recent_fails(_GLOBAL) >= _MAX_FAILS_GLOBAL

def _record_fail(ip):
    now = time.time()
    _failed_logins.setdefault(ip, []).append(now)
    _failed_logins.setdefault(_GLOBAL, []).append(now)

def _is_authenticated():
    return bool(APP_PASSWORD) and session.get('auth') == _PW_FINGERPRINT

@app.before_request
def require_login():
    if request.path in PUBLIC_PATHS or _is_authenticated():
        return None
    if request.path.startswith('/api/'):
        return jsonify({"hata": "Giriş gerekli"}), 401
    return redirect('/login')

LOGIN_HTML = """<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anı Defteri · Giriş</title>
<meta name="theme-color" content="#f8fafc">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#0f172a;padding:16px}
.card{width:100%;max-width:340px;background:#fff;border-radius:24px;padding:32px 24px;
box-shadow:0 10px 30px rgba(15,23,42,.08);text-align:center}
img{width:96px;height:96px;object-fit:contain;margin-bottom:8px}
h1{font-size:18px;margin:0 0 20px;font-weight:600}
input{width:100%;font-size:16px;padding:14px 16px;border:1px solid #e2e8f0;border-radius:14px;
outline:none;background:#f8fafc;margin-bottom:12px}
input:focus{border-color:#3b82f6;background:#fff}
button{width:100%;font-size:16px;padding:14px;border:0;border-radius:14px;background:#0f172a;
color:#fff;font-weight:600;cursor:pointer}
.err{color:#dc2626;font-size:14px;margin:0 0 12px}
</style></head><body>
<form class="card" method="post" action="/login">
<img src="/logo_son.png" alt="">
<h1>Anı Defteri</h1>
__ERROR__
<input type="password" name="sifre" placeholder="Şifre" autocomplete="current-password" autofocus required>
<button type="submit">Giriş</button>
</form></body></html>"""

def _login_page(error='', status=200):
    err_html = f'<p class="err">{error}</p>' if error else ''
    resp = Response(LOGIN_HTML.replace('__ERROR__', err_html), status=status,
                    mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method != 'POST':  # GET ve HEAD (ör. UptimeRobot) şifre denemesi değildir
        if _is_authenticated():
            return redirect('/')
        return _login_page()

    ip = _client_ip()
    if _is_locked_out(ip):
        return _login_page('Çok fazla hatalı deneme. 15 dakika sonra tekrar dene.', 429)
    if not APP_PASSWORD:
        return _login_page('Şifre sunucuda tanımlanmamış (APP_PASSWORD).', 503)

    sifre = request.form.get('sifre', '')
    if hmac.compare_digest(sifre.encode(), APP_PASSWORD.encode()):
        _failed_logins.pop(ip, None)
        session.clear()
        session.permanent = True
        session['auth'] = _PW_FINGERPRINT
        return redirect('/')

    _record_fail(ip)
    return _login_page('Şifre yanlış.', 401)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

DRIVE_FOLDER_ID = '1ALg2PFHjGWnlfl3wnzYiKTP0cG2Q-Lu4' 
SPREADSHEET_ID = '1oBL6V7UQBCKhWClRkmZ1_3YtjxUs4KjmxHQCFjzZEFY' 
RANGE_NAME = 'Sayfa1!A:H' 

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
]

# ── HİBRİT KİMLİK DOĞRULAMA ──────────────────────────────────────────────────
# Sheets  → Service Account (süresi dolmaz, okuma/yazma için)
# Drive   → OAuth token (fotoğraf yükleme için; production modda süresi dolmaz)
# ─────────────────────────────────────────────────────────────────────────────

def get_sheets_service():
    """Service Account ile Sheets bağlantısı."""
    creds = None
    try:
        sa_json = os.getenv('SERVICE_ACCOUNT_JSON')
        if sa_json:
            info = json.loads(base64.b64decode(sa_json)) if not sa_json.strip().startswith('{') else json.loads(sa_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            # Yerel ortam: önce service_account.json, yoksa credentials.json
            for sa_path in ('service_account.json', 'credentials.json'):
                if os.path.exists(sa_path):
                    creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
                    break
            else:
                print("Service account bulunamadı (SERVICE_ACCOUNT_JSON / service_account.json / credentials.json)")
    except Exception as e:
        print(f"Service account yüklenemedi: {e}")
        return None
    if creds:
        return build('sheets', 'v4', credentials=creds)
    return None

def get_drive_service():
    """OAuth token ile Drive bağlantısı (fotoğraf yükleme için)."""
    token_path = 'token.pickle'
    if not os.path.exists(token_path) and os.getenv('TOKEN_PICKLE_BASE64'):
        with open(token_path, 'wb') as f:
            f.write(base64.b64decode(os.getenv('TOKEN_PICKLE_BASE64')))
    
    creds = None
    if os.path.exists(token_path):
        try:
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            print(f"token.pickle okunamadı: {e}")
            return None
    
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)
        except Exception as e:
            print(f"Drive OAuth token yenilenemedi: {e}")
            return None

    if creds:
        return build('drive', 'v3', credentials=creds)
    return None

sheets_service = get_sheets_service()
drive_service = get_drive_service()
UPLOAD_FOLDER = 'temp_uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── In-memory cache ──────────────────────────────────────────────────────────
_sheet_cache = None
_cache_dirty = True

def get_sheet_data(force=False):
    global _sheet_cache, _cache_dirty, sheets_service
    if force or _cache_dirty or _sheet_cache is None:
        if not sheets_service:
            sheets_service = get_sheets_service()
        if not sheets_service:
            return []
        values = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME
        ).execute().get('values', [])
        _sheet_cache = values
        _cache_dirty = False
    return _sheet_cache

def invalidate_cache():
    global _cache_dirty
    _cache_dirty = True

def _fix_image_orientation(path):
    """EXIF Orientation etiketine göre pikselleri gerçekten döndürüp etiketi
    sıfırlar. Google Drive'ın thumbnail servisi EXIF Orientation'ı dikkate
    almadığı için, döndürme bilgisini yüklemeden önce piksellere işlemek
    gerekiyor; aksi halde fotoğraflar slaytta/listede ters/yan görünüyor."""
    try:
        with Image.open(path) as img:
            fixed = ImageOps.exif_transpose(img)
            if fixed is None:
                return
            save_kwargs = {}
            if img.format == 'JPEG':
                save_kwargs['quality'] = 95
            fixed.save(path, format=img.format, **save_kwargs)
    except Exception as e:
        print(f"EXIF orientation düzeltilemedi: {e}")

def upload_photo_to_drive(foto):
    """Fotoğrafı OAuth ile Drive'a yükle, thumbnail linkini döndür."""
    global drive_service
    if not drive_service:
        drive_service = get_drive_service()
    if not drive_service:
        raise Exception("Drive servisi kullanılamıyor (token eksik/geçersiz)")
    
    orijinal_isim = secure_filename(foto.filename)
    temp_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex[:8]}_{orijinal_isim}")
    foto.save(temp_path)
    _fix_image_orientation(temp_path)
    try:
        with open(temp_path, 'rb') as f:
            media = MediaIoBaseUpload(f, mimetype=foto.content_type, resumable=True)
            file = drive_service.files().create(
                body={'name': orijinal_isim, 'parents': [DRIVE_FOLDER_ID]},
                media_body=media, fields='id'
            ).execute()
            file_id = file.get('id')
            try:
                drive_service.permissions().create(
                    fileId=file_id, body={'type': 'anyone', 'role': 'reader'}
                ).execute()
            except: pass
            return f"https://drive.google.com/thumbnail?id={file_id}&sz=w800"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/anilar', methods=['GET'])
def anilari_getir():
    try:
        values = get_sheet_data()
        if not values or len(values) <= 1:
            return jsonify([])
        anilar = []
        for row in reversed(values[1:]):
            if len(row) >= 4:
                anilar.append({
                    "id": row[0], "baslik": row[1], "notlar": row[2], "tarih": row[3],
                    "gorsel_link": row[4] if len(row) > 4 else "NO_IMAGE",
                    "kategori": row[5] if len(row) > 5 else "Diğer",
                    "sub_kategori": row[6] if len(row) > 6 else "Genel",
                    "puan": row[7] if len(row) > 7 else "0"
                })
        return jsonify(anilar)
    except Exception as e:
        print(f"Anılar okunamadı: {e}")
        return jsonify([])

@app.route('/api/ani_ekle', methods=['POST'])
def ani_ekle():
    global sheets_service
    try:
        baslik = request.form.get('baslik', 'Fotoğraf')
        notlar = request.form.get('notlar', '')
        tarih = request.form.get('tarih')
        kategori = request.form.get('kategori', 'Diğer')
        sub_kategori = request.form.get('sub_kategori', 'Genel')
        puan = request.form.get('puan', 0)
        foto = request.files.get('foto')

        if not sheets_service:
            sheets_service = get_sheets_service()
        if not sheets_service:
            raise Exception("Sheets servisi kullanılamıyor (service account eksik/geçersiz)")

        gorsel_linki = "NO_IMAGE"
        if foto and foto.filename:
            gorsel_linki = upload_photo_to_drive(foto)

        sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME, valueInputOption="USER_ENTERED",
            body={"values": [[uuid.uuid4().hex[:8], baslik, notlar, tarih, gorsel_linki, kategori, sub_kategori, puan]]}
        ).execute()
        invalidate_cache()
        return jsonify({"mesaj": "Anı eklendi!"})
    except Exception as e:
        return jsonify({"hata": str(e)}), 500

@app.route('/api/ani_sil', methods=['POST'])
def ani_sil():
    global sheets_service
    ani_id = request.form.get('id')
    try:
        values = get_sheet_data(force=True)
        row_index = next((i for i, r in enumerate(values) if r and r[0] == ani_id), -1)
        if row_index == -1:
            return jsonify({"hata": "Kayıt bulunamadı"}), 404
        
        sheet_id = sheets_service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID
        ).execute()['sheets'][0]['properties']['sheetId']
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"deleteDimension": {"range": {
                "sheetId": sheet_id, "dimension": "ROWS",
                "startIndex": row_index, "endIndex": row_index + 1
            }}}]}
        ).execute()
        invalidate_cache()
        return jsonify({"mesaj": "Silindi"})
    except Exception as e:
        return jsonify({"hata": str(e)}), 500

@app.route('/api/ani_duzenle', methods=['POST'])
def ani_duzenle():
    global sheets_service
    ani_id = request.form.get('id')
    baslik = request.form.get('baslik', 'Fotoğraf')
    notlar = request.form.get('notlar', '')
    tarih = request.form.get('tarih')
    kategori = request.form.get('kategori', 'Diğer')
    sub_kategori = request.form.get('sub_kategori', 'Genel')
    puan = request.form.get('puan', 0)
    foto = request.files.get('foto')

    try:
        values = get_sheet_data(force=True)
        row_index = next((i for i, r in enumerate(values) if r and r[0] == ani_id), -1)
        if row_index == -1:
            return jsonify({"hata": "Kayıt bulunamadı"}), 404
        
        gorsel_linki = values[row_index][4] if len(values[row_index]) > 4 else "NO_IMAGE"
        if foto and foto.filename:
            gorsel_linki = upload_photo_to_drive(foto)

        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"Sayfa1!A{row_index+1}:H{row_index+1}",
            valueInputOption="USER_ENTERED",
            body={"values": [[ani_id, baslik, notlar, tarih, gorsel_linki, kategori, sub_kategori, puan]]}
        ).execute()
        invalidate_cache()
        return jsonify({"mesaj": "Güncellendi"})
    except Exception as e:
        return jsonify({"hata": str(e)}), 500

# ── DÜRTME BİLDİRİMLERİ (Web Push) ────────────────────────────────────────────
# Her cihaz bildirimleri açınca aboneliği Sheets'teki "Bildirimler" sekmesine
# kaydedilir. "Dürt" denince, gönderen cihaz hariç tüm abonelere bildirim gider.
# VAPID_PRIVATE_KEY : Web Push imza anahtarı (Render → Environment).
PUSH_SHEET = 'Bildirimler'
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY', '')
VAPID_SUB = os.getenv('VAPID_SUB', 'https://fsd-uckd.onrender.com')
_last_durt = {}

def _vapid_public_key():
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization
    raw = Vapid.from_string(VAPID_PRIVATE_KEY).public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()

def _sheets():
    global sheets_service
    if not sheets_service:
        sheets_service = get_sheets_service()
    if not sheets_service:
        raise Exception("Sheets servisi kullanılamıyor")
    return sheets_service

def _ensure_push_sheet():
    svc = _sheets()
    meta = svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    if not any(s['properties']['title'] == PUSH_SHEET for s in meta['sheets']):
        svc.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body={"requests": [
            {"addSheet": {"properties": {"title": PUSH_SHEET}}}]}).execute()
        svc.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=f"{PUSH_SHEET}!A1:C1",
            valueInputOption="RAW", body={"values": [["endpoint", "subscription", "tarih"]]}
        ).execute()
    return svc

def _load_subs():
    svc = _ensure_push_sheet()
    rows = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{PUSH_SHEET}!A2:C").execute().get('values', [])
    return [r for r in rows if len(r) >= 2]

def _save_subs(rows):
    svc = _ensure_push_sheet()
    svc.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range=f"{PUSH_SHEET}!A2:C").execute()
    if rows:
        svc.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=f"{PUSH_SHEET}!A2:C{len(rows) + 1}",
            valueInputOption="RAW", body={"values": rows}).execute()

@app.route('/api/push/public_key')
def push_public_key():
    if not VAPID_PRIVATE_KEY:
        return jsonify({"hata": "Bildirimler sunucuda ayarlanmamış (VAPID_PRIVATE_KEY)"}), 503
    return jsonify({"key": _vapid_public_key()})

@app.route('/api/push/subscribe', methods=['POST'])
def push_subscribe():
    try:
        sub = (request.get_json(silent=True) or {}).get('subscription') or {}
        endpoint = sub.get('endpoint')
        if not endpoint or not sub.get('keys'):
            return jsonify({"hata": "Geçersiz abonelik"}), 400
        rows = [r for r in _load_subs() if r[0] != endpoint]
        rows.append([endpoint, json.dumps(sub), time.strftime('%Y-%m-%d %H:%M')])
        _save_subs(rows)
        return jsonify({"mesaj": "Bildirimler açıldı"})
    except Exception as e:
        print(f"Abonelik kaydedilemedi: {e}")
        return jsonify({"hata": str(e)}), 500

@app.route('/api/push/hata', methods=['POST'])
def push_hata():
    """Telefonda bildirim açılırken oluşan hatayı Render loglarına yazar."""
    d = request.get_json(silent=True) or {}
    print(f"Bildirim istemci hatası: {str(d.get('hata'))[:300]} | UA: {request.headers.get('User-Agent', '')[:150]}")
    return jsonify({"mesaj": "kaydedildi"})

@app.route('/api/push/unsubscribe', methods=['POST'])
def push_unsubscribe():
    try:
        endpoint = (request.get_json(silent=True) or {}).get('endpoint')
        rows = _load_subs()
        kalan = [r for r in rows if r[0] != endpoint]
        if len(kalan) != len(rows):
            _save_subs(kalan)
        return jsonify({"mesaj": "Bildirimler kapatıldı"})
    except Exception as e:
        return jsonify({"hata": str(e)}), 500

@app.route('/api/push/durt', methods=['POST'])
def push_durt():
    from pywebpush import webpush, WebPushException
    if not VAPID_PRIVATE_KEY:
        return jsonify({"hata": "Bildirimler sunucuda ayarlanmamış"}), 503
    sender = (request.get_json(silent=True) or {}).get('endpoint') or ''

    # Arka arkaya basmaya karşı: aynı cihazdan 5 saniyede bir
    now = time.time()
    if now - _last_durt.get(sender, 0) < 5:
        return jsonify({"hata": "Biraz bekle 🙂"}), 429
    _last_durt[sender] = now

    try:
        rows = _load_subs()
        hedefler = [r for r in rows if r[0] != sender]
        if not hedefler:
            return jsonify({"hata": "Karşı tarafta bildirimler henüz açık değil"}), 404
        payload = json.dumps({"title": "Anı Defteri", "body": "💙 Seni düşünüyorum"})
        gonderilen, olu = 0, set()
        for r in hedefler:
            try:
                webpush(subscription_info=json.loads(r[1]), data=payload,
                        vapid_private_key=VAPID_PRIVATE_KEY,
                        vapid_claims={"sub": VAPID_SUB}, ttl=3600,
                        headers={"Urgency": "high"})
                gonderilen += 1
            except WebPushException as e:
                code = getattr(e.response, 'status_code', None)
                print(f"Bildirim gönderilemedi ({code}): {e}")
                if code in (404, 410):  # abonelik süresi dolmuş/iptal edilmiş
                    olu.add(r[0])
        if olu:
            _save_subs([r for r in rows if r[0] not in olu])
        if not gonderilen:
            return jsonify({"hata": "Bildirim gönderilemedi, karşı taraf bildirimleri yeniden açmalı"}), 502
        return jsonify({"mesaj": "Gönderildi", "adet": gonderilen})
    except Exception as e:
        print(f"Dürtme hatası: {e}")
        return jsonify({"hata": str(e)}), 500

# ── Static file routes ────────────────────────────────────────────────────────

@app.route('/')
def index():
    response = send_from_directory('public', 'index.html')
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/sw.js')
def service_worker():
    response = send_from_directory('public', 'sw.js')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Content-Type'] = 'application/javascript'
    return response

@app.route('/manifest.json')
def manifest():
    return send_from_directory('public', 'manifest.json')

@app.route('/<path:path>')
def serve_public(path):
    return send_from_directory('public', path)

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG', '1') == '1')