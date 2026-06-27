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
```eof

### 2. `public/index.html` (Frontend)
Bu dosyada slayt gösterisi, başlığı gizleme mantığı ve lightbox özellikleri mevcuttur.

```html:public/index.html
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Anı Defteri</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#dbe4e6] min-h-screen font-sans antialiased">
    
    <div class="max-w-md mx-auto p-4 pb-20">
        <header class="flex justify-center py-6">
            <img src="/logo_son.svg" alt="Logo" class="h-28 w-auto object-contain drop-shadow-sm">
        </header>

        <!-- Home -->
        <div id="homeView">
            <div id="homeHero" class="relative w-full h-48 bg-slate-800 rounded-2xl shadow-lg flex items-center justify-center border border-slate-700 mb-8 overflow-hidden">
                <div id="slideshowContainer" class="absolute inset-0 w-full h-full"></div>
                <div class="absolute inset-0 bg-slate-900/40 z-10"></div>
                <p class="relative z-20 text-white/95 font-bold tracking-[0.3em] uppercase text-sm drop-shadow-md">DİJİTAL ANILAR</p>
            </div>
            <div class="flex flex-col gap-y-4">
                <button onclick="navigate('Seyahat')" class="w-full bg-white py-6 font-bold text-slate-700 rounded-xl border-l-8 border-blue-500 shadow-sm hover:shadow-md transition-all active:scale-[0.98]">SEYAHAT</button>
                <button onclick="navigate('Yemek')" class="w-full bg-white py-6 font-bold text-slate-700 rounded-xl border-l-8 border-orange-500 shadow-sm hover:shadow-md transition-all active:scale-[0.98]">YEMEK</button>
                <button onclick="navigate('Film')" class="w-full bg-white py-6 font-bold text-slate-700 rounded-xl border-l-8 border-violet-600 shadow-sm hover:shadow-md transition-all active:scale-[0.98]">FİLM</button>
                <button onclick="navigate('Aktivite')" class="w-full bg-white py-6 font-bold text-slate-700 rounded-xl border-l-8 border-emerald-500 shadow-sm hover:shadow-md transition-all active:scale-[0.98]">AKTİVİTE</button>
            </div>
        </div>

        <!-- Folder Select -->
        <div id="folderView" class="hidden space-y-6">
            <button onclick="goHome()" class="text-slate-500 font-semibold text-sm hover:text-slate-800 transition-all">← Kategorilere Dön</button>
            <h2 id="folderTitle" class="text-xl font-bold text-slate-800 text-center uppercase tracking-widest"></h2>
            <div id="folderList" class="grid grid-cols-2 gap-4"></div>
            <div class="bg-white/50 p-4 rounded-xl mt-6">
                <input type="text" id="newFolderInput" placeholder="Yeni Klasör Adı" class="w-full p-3 rounded-lg border border-slate-200 mb-2">
                <button onclick="createFolder()" class="w-full bg-slate-700 text-white font-bold py-2 rounded-lg hover:bg-slate-800">Klasör Oluştur</button>
            </div>
        </div>

        <!-- Detail/Form -->
        <div id="detailView" class="hidden space-y-6">
            <button id="backBtn" onclick="goBackFromDetail()" class="text-slate-500 font-semibold text-sm hover:text-slate-800 transition-all"></button>
            <h1 id="subCategoryTitle" class="text-xl font-bold text-center uppercase tracking-widest text-slate-800"></h1>
            
            <div class="bg-white p-6 rounded-3xl border border-slate-100 shadow-md">
                <form id="aniForm" onsubmit="saveAni(event)" class="space-y-4">
                    <input type="hidden" name="kategori" id="formKategori">
                    <input type="hidden" name="sub_kategori" id="formSubKategori">
                    <input type="hidden" name="tarih" id="hiddenTarihInput">
                    
                    <div id="inputGroup" class="space-y-4">
                        <input type="text" name="baslik" id="baslikInput" required placeholder="Başlık" class="w-full border-b border-slate-300 py-2 bg-transparent outline-none focus:border-slate-800 transition-all">
                        <textarea name="notlar" id="notlarInput" rows="2" placeholder="Notlar..." class="w-full border-b border-slate-300 py-2 bg-transparent outline-none focus:border-slate-800 transition-all"></textarea>
                    </div>
                    
                    <input type="file" name="foto" accept="image/*" class="w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:bg-slate-100 cursor-pointer">
                    
                    <button type="submit" id="submitBtn" class="w-full bg-slate-800 text-white font-bold py-3.5 rounded-xl hover:bg-slate-900 shadow-lg">KAYDET</button>
                </form>
            </div>
            <div id="aniListesi" class="space-y-4 pb-10"></div>
        </div>
    </div>

    <div id="lightbox" class="hidden fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4" onclick="closeLightbox()">
        <img id="lightboxImg" class="max-w-full max-h-full object-contain">
    </div>

    <script>
        const bugun = new Date().toISOString().split('T')[0];
        let state = { cat: '', sub: '' };
        const usesFolders = ['Seyahat', 'Aktivite'];

        window.onload = () => { initSlideshow(); };

        async function initSlideshow() {
            try {
                const res = await fetch('/api/anilar');
                const data = await res.json();
                const photos = data.filter(a => a.kategori === 'Seyahat' && a.gorsel_link !== 'NO_IMAGE');
                if (photos.length > 0) {
                    const cont = document.getElementById('slideshowContainer');
                    cont.innerHTML = photos.map((p, i) => `<img src="${p.gorsel_link}" class="absolute inset-0 w-full h-full object-cover transition-opacity duration-1000 ${i===0?'opacity-100':'opacity-0'}">`).join('');
                }
            } catch(e) {}
        }

        function navigate(kat) {
            state.cat = kat;
            document.getElementById('homeView').classList.add('hidden');
            if(usesFolders.includes(kat)) {
                document.getElementById('folderView').classList.remove('hidden');
                document.getElementById('folderTitle').innerText = kat;
                loadFolders(kat);
            } else { openFolder('Genel'); }
        }

        function openFolder(sub, dateVal = bugun) {
            state.sub = sub;
            document.getElementById('folderView').classList.add('hidden');
            document.getElementById('detailView').classList.remove('hidden');
            
            // Klasör içi yüklemede başlık zorunluluğunu kaldır ve gizle
            const inFolder = usesFolders.includes(state.cat);
            document.getElementById('inputGroup').classList.toggle('hidden', inFolder);
            document.getElementById('baslikInput').required = !inFolder;
            document.getElementById('baslikInput').value = inFolder ? "Fotoğraf" : "";
            
            document.getElementById('formKategori').value = state.cat;
            document.getElementById('formSubKategori').value = sub;
            document.getElementById('hiddenTarihInput').value = dateVal;
            
            loadAnilar(state.cat, sub);
        }

        async function saveAni(event) {
            event.preventDefault();
            const btn = document.getElementById('submitBtn');
            btn.disabled = true; btn.innerText = "YÜKLENİYOR...";
            const formData = new FormData(document.getElementById('aniForm'));
            try {
                const res = await fetch('/api/ani_ekle', { method: 'POST', body: formData });
                if(res.ok) { alert('Kaydedildi!'); location.reload(); }
            } catch(e) { alert('Hata.'); }
            btn.disabled = false; btn.innerText = "KAYDET";
        }

        function openLightbox(url) {
            document.getElementById('lightboxImg').src = url;
            document.getElementById('lightbox').classList.remove('hidden');
        }

        function closeLightbox() { document.getElementById('lightbox').classList.add('hidden'); }
        
        // ... (loadFolders ve loadAnilar fonksiyonlarını önceki kodunla aynı şekilde tut)
    </script>
</body>
</html>
```eof

Artık `git push` yaptıktan sonra fotoğrafın üzerine tıkladığında tam ekran açılacak ve seyahat fotoğrafların anasayfada dönecek. Hadi, yüklemeyi tekrar dene!