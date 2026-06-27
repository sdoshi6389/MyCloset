import os
import io
import pickle
import psycopg2
from tqdm import tqdm
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# === CONFIG ===
IMAGE_FOLDER = "downloaded_images"
CREDENTIALS_PATH = "credentials.json"
TOKEN_PATH = "token.pickle"
DRIVE_FOLDER_ID = "1z6E8qdIgxzu_aGBeWTH9XWGD010am4iH"
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

DB_CONFIG = {
    "dbname": "your_dbname",
    "user": "your_user",
    "password": "your_password",
    "host": "localhost",
    "port": 5432
}

# === Google Drive Authentication ===
def authenticate_drive():
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'wb') as token:
            pickle.dump(creds, token)
    return build('drive', 'v3', credentials=creds)

# === Download Images ===
def download_and_log_images(service, folder_id, output_folder):
    os.makedirs(output_folder, exist_ok=True)
    query = f"'{folder_id}' in parents and mimeType contains 'image/'"
    results = service.files().list(q=query, pageSize=1000, fields="files(id, name)").execute()
    items = results.get('files', [])

    for item in tqdm(items, desc="Downloading from Drive"):
        file_id = item['id']
        file_name = item['name']
        local_path = os.path.join(output_folder, file_name)

        # Download the image
        request = service.files().get_media(fileId=file_id)
        with open(local_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

if __name__ == "__main__":
    print("Authenticating with Google Drive...")
    service = authenticate_drive()

    print("Downloading images...")
    download_and_log_images(service, DRIVE_FOLDER_ID, IMAGE_FOLDER)

    print("Done! Images downloaded.")
