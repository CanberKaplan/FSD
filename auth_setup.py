from google_auth_oauthlib.flow import InstalledAppFlow
import pickle

# HEM DRIVE HEM DE SHEETS YETKİSİ EKLENDİ
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
]

# client_secrets.json dosyanızın bulunduğu klasörde çalıştırın
flow = InstalledAppFlow.from_client_secrets_file('client_secrets.json', SCOPES)
creds = flow.run_local_server(port=8080)

with open('token.pickle', 'wb') as token:
    pickle.dump(creds, token)
print("token.pickle başarıyla oluşturuldu!")