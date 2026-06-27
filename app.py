import os
import uuid
import traceback
import pickle
import base64
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

app = Flask(__name__, static_folder='public')

# ==========================================
# 1. GOOGLE DRIVE VE SHEETS BAĞLANTISI
# ==========================================
DRIVE_FOLDER_ID = '1ALg2PFHjGWnlfl3wnzYiKTP0cG2Q-Lu4' 
# Sadece tablo ID'si (URL'in tamamı değil)
SPREADSHEET_ID = '1oBL6V7UQBCKhWClRkmZ1_3YtjxUs4KjmxHQCFjzZEFY' 
RANGE_NAME = 'Sayfa1!A:E' 

drive_service = None
sheets_service = None

def get_google_services():
    token_path = 'token.pickle'
    
    # EĞER DOSYA YOKSA VE ENV VARSAYSA OLUŞTUR
    if not os.path.exists(token_path) and os.getenv('TOKEN_PICKLE_BASE64'):
        with open(token_path, 'wb') as f:
            f.write(base64.b64decode(os.getenv('TOKEN_PICKLE_BASE64')))

    creds = None
    if os.path.exists(token_path):
        try:
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            print(f"Token okuma hatası: {e}")
            return None, None
    
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)
        except Exception as e:
            print(f"Token yenileme hatası: {e}")
            return None, None
            
    if creds:
        d_service = build('drive', 'v3', credentials=creds)
        s_service = build('sheets', 'v4', credentials=creds)
        return d_service, s_service
    return None, None

drive_service, sheets_service = get_google_services()

UPLOAD_FOLDER = 'temp_uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==========================================
# 2. API UÇ NOKTALARI
# ==========================================

@app.route('/api/anilar', methods=['GET'])
def anilari_getir():
    global sheets_service
    if not sheets_service:
        _, sheets_service = get_google_services()
        if not sheets_service:
            return jsonify([]) 
             
    try:
        sheet = sheets_service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        values = result.get('values', [])

        if not values or len(values) == 1:
            return jsonify([])

        anilar = []
        for row in reversed(values[1:]):
            if len(row) >= 5:
                anilar.append({
                    "id": row[0],
                    "baslik": row[1],
                    "notlar": row[2],
                    "tarih": row[3],
                    "gorsel_link": row[4]
                })
        return jsonify(anilar)
    except Exception as e:
        traceback.print_exc()
        return jsonify([])

@app.route('/api/ani_ekle', methods=['POST'])
def ani_ekle():
    global drive_service, sheets_service
    if not drive_service or not sheets_service:
        drive_service, sheets_service = get_google_services()
        if not drive_service:
            return jsonify({"hata": "Google servisleri başlatılamadı."}), 500

    temp_path = None
    try:
        baslik = request.form.get('baslik')
        notlar = request.form.get('notlar')
        tarih = request.form.get('tarih')
        foto = request.files.get('foto')

        if not foto:
            return jsonify({"hata": "Fotoğraf seçilmedi"}), 400

        orijinal_isim = secure_filename(foto.filename)
        benzersiz_isim = f"{uuid.uuid4().hex[:8]}_{orijinal_isim}"
        temp_path = os.path.join(UPLOAD_FOLDER, benzersiz_isim)
        foto.save(temp_path)

        file_metadata = {'name': orijinal_isim, 'parents': [DRIVE_FOLDER_ID]}
        with open(temp_path, 'rb') as f:
            media = MediaIoBaseUpload(f, mimetype=foto.content_type, resumable=True)
            drive_file = drive_service.files().create(
                body=file_metadata, 
                media_body=media, 
                fields='id'
            ).execute()
        
        file_id = drive_file.get('id')
        dogrudan_gorsel_linki = f"https://docs.google.com/uc?export=view&id={file_id}"

        ani_id = uuid.uuid4().hex[:8]
        yeni_satir = [[ani_id, baslik, notlar, tarih, dogrudan_gorsel_linki]]
        
        sheet = sheets_service.spreadsheets()
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": yeni_satir}
        ).execute()

        if os.path.exists(temp_path): os.remove(temp_path)
        return jsonify({"mesaj": "Anı eklendi!"})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"hata": str(e)}), 500

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/<path:path>')
def serve_public(path):
    return send_from_directory('public', path)

if __name__ == '__main__':
    app.run()