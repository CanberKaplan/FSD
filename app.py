# ... existing code ...
# ==========================================
# 1. GOOGLE DRIVE VE SHEETS BAĞLANTISI
# ==========================================
DRIVE_FOLDER_ID = '1ALg2PFHjGWnlfl3wnzYiKTP0cG2Q-Lu4' 
# BURAYI KENDI TABLO ID'NIZ ILE DEGISTIRIN:
SPREADSHEET_ID = '1oBL6V7UQBCKhWClRkmZ1_3YtjxUs4KjmxHQCFjzZEFY' 
RANGE_NAME = 'Sayfa1!A:G' # Tablonuzun alt sekme ismi "Sayfa1" (veya "Sheet1") olmalıdır.

drive_service = None
# ... existing code ...
@app.route('/api/anilar', methods=['GET'])
def anilari_getir():
    global sheets_service
    if not sheets_service:
        _, sheets_service = get_google_services()
        if not sheets_service:
             return jsonify([]) # Hata varsa boş liste dön
             
    try:
        sheet = sheets_service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        values = result.get('values', [])

        if not values or len(values) == 1: # Sadece başlıklar varsa
            return jsonify([])

        anilar = []
        # İlk satırı (başlıkları) atlayarak tersten oku (En yeni en üstte)
        for row in reversed(values[1:]):
            if len(row) >= 7: # Satırın tam olduğundan emin ol
                anilar.append({
                    "id": row[0],
                    "baslik": row[1],
                    "notlar": row[2],
                    "tarih": row[3],
                    "gorsel_link": row[4],
                    "kategori": row[5],
                    "puan": row[6] # Yeni alan
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
        kategori = request.form.get('kategori')
        puan = request.form.get('puan', 0)

        if not foto:
            return jsonify({"hata": "Fotoğraf seçilmedi"}), 400
# ... existing code ...
        file_id = drive_file.get('id')
        dogrudan_gorsel_linki = f"https://docs.google.com/uc?export=view&id={file_id}"

        # 2. Verileri Google Sheets'e Kaydet
        ani_id = uuid.uuid4().hex[:8]
        yeni_satir = [[ani_id, baslik, notlar, tarih, dogrudan_gorsel_linki, kategori, puan]]
        
        sheet = sheets_service.spreadsheets()
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": yeni_satir}
        ).execute()

        if os.path.exists(temp_path): os.remove(temp_path)
# ... existing code ...