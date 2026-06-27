import os
import sqlite3
import uuid
import traceback
import pickle
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

app = Flask(__name__, static_folder='public')

DRIVE_FOLDER_ID = '1ALg2PFHjGWnlfl3wnzYiKTP0cG2Q-Lu4' 
drive_service = None

def get_drive_service():
    # 1. Kendi klasöründe ara, 2. Render'ın Secret Files klasöründe ara
    possible_paths = ['token.pickle', '/etc/secrets/token.pickle']
    token_path = None
    
    for path in possible_paths:
        if os.path.exists(path):
            token_path = path
            break
    
    if not token_path:
        print("HATA: token.pickle hiçbir yerde bulunamadı!")
        return None

    creds = None
    try:
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)
    except Exception as e:
        print(f"Token okuma hatası: {e}")
        return None
    
    # Token süresi dolduysa yenile (yazma yetkisi olmayabilir, dikkat)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"Token yenileme hatası: {e}")
            
    return build('drive', 'v3', credentials=creds)

# Uygulama başlarken bağlantıyı kur
drive_service = get_drive_service()

UPLOAD_FOLDER = 'temp_uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ... (init_db ve diğer API uç noktaları aynı kalacak, aşağıya ekledim) ...

def init_db():
    conn = sqlite3.connect('anilar.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS anilar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            baslik TEXT NOT NULL,
            notlar TEXT,
            tarih TEXT,
            drive_file_id TEXT,
            gorsel_link TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/api/anilar', methods=['GET'])
def anilari_getir():
    conn = sqlite3.connect('anilar.db')
    c = conn.cursor()
    c.execute("SELECT * FROM anilar ORDER BY id DESC")
    anilar = [{"id": r[0], "baslik": r[1], "notlar": r[2], "tarih": r[3], "gorsel_link": r[5]} for r in c.fetchall()]
    conn.close()
    return jsonify(anilar)

@app.route('/api/ani_ekle', methods=['POST'])
def ani_ekle():
    if not drive_service:
        return jsonify({"hata": "Drive servisi başlatılamadı. token.pickle dosyasını Render'a 'Secret File' olarak eklediğinizden emin olun."}), 500

    temp_path = None
    try:
        baslik = request.form.get('baslik')
        notlar = request.form.get('notlar')
        tarih = request.form.get('tarih')
        foto = request.files.get('foto')
        if not foto: return jsonify({"hata": "Fotoğraf seçilmedi"}), 400

        orijinal_isim = secure_filename(foto.filename)
        benzersiz_isim = f"{uuid.uuid4().hex[:8]}_{orijinal_isim}"
        temp_path = os.path.join(UPLOAD_FOLDER, benzersiz_isim)
        foto.save(temp_path)

        file_metadata = {'name': orijinal_isim, 'parents': [DRIVE_FOLDER_ID]}
        with open(temp_path, 'rb') as f:
            media = MediaIoBaseUpload(f, mimetype=foto.content_type, resumable=True)
            drive_file = drive_service.files().create(
                body=file_metadata, media_body=media, fields='id'
            ).execute()
        
        file_id = drive_file.get('id')
        dogrudan_gorsel_linki = f"https://docs.google.com/uc?export=view&id={file_id}"

        conn = sqlite3.connect('anilar.db')
        c = conn.cursor()
        c.execute('INSERT INTO anilar (baslik, notlar, tarih, drive_file_id, gorsel_link) VALUES (?, ?, ?, ?, ?)',
                  (baslik, notlar, tarih, file_id, dogrudan_gorsel_linki))
        conn.commit()
        conn.close()

        if os.path.exists(temp_path): os.remove(temp_path)
        return jsonify({"mesaj": "Anı eklendi!"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"hata": str(e)}), 500

@app.route('/')
def index(): return send_from_directory('public', 'index.html')

@app.route('/<path:path>')
def serve_public(path): return send_from_directory('public', path)

if __name__ == '__main__':
    app.run()
```

### Ne yapmalısın?
1.  Render'da **"Secret Files"** kısmına `token.pickle` dosyasını yüklediğinden emin ol.
2.  Bu güncellenmiş `app.py` kodunu `git add`, `git commit` ve `git push` ile gönder.
3.  Render'ın loglarına tekrar bak. Artık `HATA: token.pickle hiçbir yerde bulunamadı!` yazısını alıyorsan, dosya yükleme kısmında veya isminde bir sorun var demektir.

Loglarda bu sefer daha net bir hata göreceğiz. Eğer yine çalışmazsa, **Render Logs kısmındaki "HATA" yazan o satırı buraya kopyala**, hatanın kaynağını kesin olarak tespit edelim.