import os
import uuid
import json
import pickle
import base64
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

app = Flask(__name__, static_folder='public')

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
        elif os.path.exists('service_account.json'):
            creds = service_account.Credentials.from_service_account_file('service_account.json', scopes=SCOPES)
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
        except Exception:
            return None
    
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)
        except Exception:
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
    except Exception:
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

# ── Static file routes ────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

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
    app.run(debug=True)