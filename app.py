import os
import uuid
import pickle
import base64
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

app = Flask(__name__, static_folder='public')

DRIVE_FOLDER_ID = '1ALg2PFHjGWnlfl3wnzYiKTP0cG2Q-Lu4' 
SPREADSHEET_ID = '1oBL6V7UQBCKhWClRkmZ1_3YtjxUs4KjmxHQCFjzZEFY' 
RANGE_NAME = 'Sayfa1!A:H' 

def get_google_services():
    token_path = 'token.pickle'
    if not os.path.exists(token_path) and os.getenv('TOKEN_PICKLE_BASE64'):
        with open(token_path, 'wb') as f:
            f.write(base64.b64decode(os.getenv('TOKEN_PICKLE_BASE64')))
    
    creds = None
    if os.path.exists(token_path):
        try:
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)
        except Exception: return None, None
    
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)
        except Exception: return None, None
            
    if creds:
        return build('drive', 'v3', credentials=creds), build('sheets', 'v4', credentials=creds)
    return None, None

drive_service, sheets_service = get_google_services()
UPLOAD_FOLDER = 'temp_uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/api/anilar', methods=['GET'])
def anilari_getir():
    global sheets_service
    try:
        if not sheets_service: _, sheets_service = get_google_services()
        if not sheets_service: return jsonify([])
        
        values = sheets_service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute().get('values', [])
        if not values or len(values) <= 1: return jsonify([])
        
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
    except Exception: return jsonify([])

@app.route('/api/ani_ekle', methods=['POST'])
def ani_ekle():
    global drive_service, sheets_service
    if not drive_service or not sheets_service:
        drive_service, sheets_service = get_google_services()

    try:
        baslik = request.form.get('baslik', 'Fotoğraf')
        notlar = request.form.get('notlar', '')
        tarih = request.form.get('tarih')
        kategori = request.form.get('kategori', 'Diğer')
        sub_kategori = request.form.get('sub_kategori', 'Genel')
        puan = request.form.get('puan', 0)
        foto = request.files.get('foto')

        dogrudan_gorsel_linki = "NO_IMAGE"

        if foto and foto.filename:
            orijinal_isim = secure_filename(foto.filename)
            temp_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex[:8]}_{orijinal_isim}")
            foto.save(temp_path)
            with open(temp_path, 'rb') as f:
                media = MediaIoBaseUpload(f, mimetype=foto.content_type, resumable=True)
                file = drive_service.files().create(body={'name': orijinal_isim, 'parents': [DRIVE_FOLDER_ID]}, media_body=media, fields='id, webViewLink').execute()
                file_id = file.get('id')
                dogrudan_gorsel_linki = file.get('webViewLink')
                
                try:
                    drive_service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
                except: pass
            os.remove(temp_path)

        sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME, valueInputOption="USER_ENTERED",
            body={"values": [[uuid.uuid4().hex[:8], baslik, notlar, tarih, dogrudan_gorsel_linki, kategori, sub_kategori, puan]]}
        ).execute()

        return jsonify({"mesaj": "Anı eklendi!"})
    except Exception as e:
        return jsonify({"hata": str(e)}), 500

@app.route('/')
def index(): return send_from_directory('public', 'index.html')

@app.route('/<path:path>')
def serve_public(path): return send_from_directory('public', path)

if __name__ == '__main__':
    app.run(debug=True)


