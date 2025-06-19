#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot.py – Telegram-Geschichtenkiosk mit PayPal-Integration und Google Drive PDF-Download

Autor: Fischi (2025)
Lizenz: MIT
Beschreibung:
Ein Telegram-Bot, der es Benutzern ermöglicht, Kinderbücher für 1,19€ zu kaufen.
Die Bezahlung erfolgt via PayPal. Nach erfolgreicher Zahlung wird das entsprechende PDF
aus Google Drive geladen und dem Benutzer gesendet.

Abhängigkeiten:
- pyTelegramBotAPI (telebot)
- google-api-python-client
- google-auth
- requests

Start:
python3 bot.py
"""

import io
import logging
import requests
from telebot import TeleBot, types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from config import BOT_TOKEN, PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_MODE, WEBHOOK_URL

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Bot Setup ---
bot = TeleBot(BOT_TOKEN)
bot.remove_webhook()
user_state = {}

# --- Google Drive Setup ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

# --- PDF Mapping (gekürzt) ---
PDF_FILES = {
    "Lilly und der Regenbogenschirm": "112CF9AOH8MbOZyZkgVN4UdlvZrjQdDhq",
    "Finns Flaschenpost aus dem Meer": "1nZH5ncjgEP6klYbhAJcGEiU5vH-ISD_U",
    "Mila und der sprechende Mond": "1yLGuI-L9P4xJ7n6c41hn5WRXTeiFg_8X",
    "Oskar und die verlorene Zeit": "1xaM9LvUXF5Zw4AvF9RS1PNuWp1UJOm9O",
    "Niko und der Wunschbaum": "1RlNlM1Szf8yZ8J96zQTvMWbdpyxGqL2g",
    "Sophie und der Kater aus der Zukunft": "1Sw4rO_yRTJtxZ-RIfUTKCTaNZ_Mz0dLr",
    "Emil und der Wolkenträumer": "1ImCeBJvI50oUO2TcQqI4XIkHbAq-yoRj",
    "Tom und das verschwundene Geräusch": "1onKW5TSvF9iwB_p3YX_cnuZbiFCM7fKb",
    "Lena und die fliegende Bibliothek": "1yOg_WwqN6qG4PBnZo9MiNF9rg10yI1DL",
    "Paul und das Lächeln der Sterne": "1B-XRC_b0lWBVLlHPI89Ro7WEdXPRvEIf",
    "Clara und die Glühwürmchenmelodie": "1GKnE0wEKIrfOhhUtRzxZAxpdcTv3kRQZ",
    "Jonas und das Geheimnis im Spiegel": "1zhGrxBaMkSwzPUJNSGp_C3S1OGrAfe6Y",
    "Ella und der Traumfänger": "1U9HgETk3kVxohQ6Fq82L5WlGfWwXodYX",
    "Ben und die Farben der Stille": "1VOtxCZ7-rl1gHdTCUmI5jVDtMsoch2Tf",
    "Greta und die Reise in die Schneeflocke": "1rMxyrrbd9B2VYd3TqlBICmqtHgDcojXN",
    "Lea und der Garten der Gedanken": "1xYkoFbeuW5PMxJZtE5sGmGuFJsmhKMiI",
    "Max und der flüsternde Wald": "1GHXnZ9TTnmXYeJvPKcAZuNedpxcWlko1",
    "Tilda und das Licht unter dem Bett": "1etoh5JNY4ITyNH0zldqt8lmYr_3w_Q3f",
    "Noah und die Zeitreisenuhr": "1kCt8bbllrzCm_JNHRWuHdZ3oNiW_mXeP",
    "Hannah und der singende Stein": "1AYq3gAhdTL9Ep4nHjo2U2gBeoYB9F8Lr"
}

# --- PAYPAL ---
def get_access_token():
    url = f"https://api-m.{ 'paypal.com' if PAYPAL_MODE == 'live' else 'sandbox.paypal.com' }/v1/oauth2/token"
    try:
        response = requests.post(
            url,
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
            data={"grant_type": "client_credentials"}
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        logger.info("Access Token erfolgreich abgerufen.")
        return token
    except requests.RequestException:
        logger.exception("Fehler beim Abrufen des Access Tokens.")
        raise

def create_payment(title: str, user_id: int) -> tuple[str, str]:
    access_token = get_access_token()
    base_url = "paypal.com" if PAYPAL_MODE == "live" else "sandbox.paypal.com"
    url = f"https://api-m.{base_url}/v2/checkout/orders"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"{user_id}-{title}",
            "amount": {"currency_code": "EUR", "value": "1.19"},
            "description": title
        }],
        "application_context": {
            "brand_name": "Geschichtenkiosk",
            "user_action": "PAY_NOW",
            "return_url": f"{WEBHOOK_URL}/return",
            "cancel_url": f"{WEBHOOK_URL}/cancel"
        }
    }
    response = requests.post(url, json=body, headers=headers)
    response.raise_for_status()
    data = response.json()
    order_id = data["id"]
    approval_url = next(link["href"] for link in data["links"] if link["rel"] == "approve")

    # Speichern des State anhand der order_id
    user_state[order_id] = {"chat_id": user_id, "title": title}
    return order_id, approval_url

def check_payment(order_id: str) -> bool:
    access_token = get_access_token()
    base_url = "paypal.com" if PAYPAL_MODE == "live" else "sandbox.paypal.com"
    url = f"https://api-m.{base_url}/v2/checkout/orders/{order_id}"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        status = response.json().get("status")
        return status in ["COMPLETED", "APPROVED"]
    except requests.RequestException:
        logger.exception("Fehler beim Überprüfen der Bestellung.")
        return False

# --- Drive PDF Download ---
def download_pdf(file_id):
    try:
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        return fh
    except Exception:
        logger.exception("Download-Fehler.")
        return None

# --- NEU: Flask App für PayPal Return/Capture ---
from flask import Flask, request

app = Flask(__name__)

def capture_payment(order_id: str) -> bool:
    access_token = get_access_token()
    base_url = "paypal.com" if PAYPAL_MODE == "live" else "sandbox.paypal.com"
    url = f"https://api-m.{base_url}/v2/checkout/orders/{order_id}/capture"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    try:
        response = requests.post(url, headers=headers)
        response.raise_for_status()
        logger.info(f"Zahlung {order_id} erfolgreich captured.")
        return True
    except requests.RequestException:
        logger.exception("Fehler beim Capturen der Zahlung.")
        return False

@app.route("/return")
def paypal_return():
    order_id = request.args.get("token")
    if not order_id or order_id not in user_state:
        return "Ungültige Bestellung oder nicht gefunden.", 400

    chat_id = user_state[order_id]["chat_id"]
    title = user_state[order_id]["title"]
    # State löschen, damit nicht erneut verarbeitet wird
    user_state.pop(order_id)

    if capture_payment(order_id):
        pdf = download_pdf(PDF_FILES[title])
        if pdf:
            bot.send_document(chat_id, pdf, visible_file_name=f"{title}.pdf")
            bot.send_message(chat_id, "🎉 Danke für deinen Kauf! "
                                      "Mit deiner Unterstützung hilfst du unseren kleinen Geschichtenzauberern, "
                                      "ihre Träume zu leben und unsere Familie auf kleine Abenteuer zu schicken. "
                                      "Wir freuen uns riesig, dich bald mit neuen spannenden Geschichten überraschen zu dürfen! 📚✨\n"
                                      "Viel Spaß beim Lesen! 🎉")
            return "Zahlung abgeschlossen! PDF wird im Telegram-Chat gesendet."
        else:
            return "Fehler beim Herunterladen des PDFs.", 500
    else:
        return "Zahlung konnte nicht abgeschlossen werden.", 500

@app.route("/cancel")
def paypal_cancel():
    return "Zahlung abgebrochen. Du kannst den Kauf jederzeit neu starten."

# --- Telegram Bot Handlers ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    # Neue Begrüßung beim Betreten (so früh wie möglich)
    bot.send_message(message.chat.id,
                     "👋 Hallo und herzlich willkommen im Geschichtenkiosk!\n\n"
                     "Unsere Kinder hatten die tolle Idee, ein Sparkonto für ihre Urlaubswünsche anzulegen. "
                     "Mit deinem Kauf hilfst du uns dabei, ihnen ihre Träume zu erfüllen.\n\n"
                     "So funktioniert's:\n"
                     "1️⃣ Wähle eine Geschichte aus den Buttons aus.\n"
                     "2️⃣ Du wirst zur Bezahlung weitergeleitet.\n"
                     "3️⃣ Nach erfolgreicher Zahlung erhältst du direkt deine Geschichte als PDF.\n\n"
                     "Preis pro Geschichte: 1,19€\n\n"
                     "Viel Spaß beim Stöbern und Lesen! 📚")

    markup = InlineKeyboardMarkup()
    for title in PDF_FILES:
        markup.add(InlineKeyboardButton(text=title, callback_data=f"buy_{title}"))
    bot.send_message(message.chat.id,
                     "Bitte wähle eine Geschichte aus:",
                     reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_purchase(call):
    chat_id = call.message.chat.id
    title = call.data.replace("buy_", "")
    try:
        order_id, approval_url = create_payment(title, chat_id)
        # user_state wird bereits im create_payment gespeichert
        bot.send_message(chat_id,
                         f"✅ *{title}* ausgewählt.\n"
                         f"Bitte bezahle hier: {approval_url}\n\n"
                         f"Nach erfolgreicher Zahlung wirst du automatisch deine Geschichte erhalten.",
                         parse_mode="Markdown")
    except Exception:
        bot.send_message(chat_id, "❌ Fehler beim Erstellen der Zahlung.")

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    print("✅ Telegram-Update empfangen!")  # <-- Log-Zeile hinzufügen
    json_string = request.get_data().decode("utf-8")
    update = types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return jsonify({"status": "ok"})

@app.route("/", methods=["GET"])
def home():
    return "Webhook läuft ✅", 200

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host="0.0.0.0", port=5000)
