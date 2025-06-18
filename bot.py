#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot.py – Telegram-Geschichtenkiosk mit PayPal-Integration und Google Drive PDF-Download

Autor: Fischi (2025)
Lizenz: MIT
Beschreibung:
Ein Telegram-Bot, der es Benutzern ermöglicht, Kinderbücher für 0,99€ zu kaufen.
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
from config import BOT_TOKEN, PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_MODE

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
    url = f"https://api-m.{PAYPAL_MODE}.paypal.com/v1/oauth2/token"
    try:
        response = requests.post(
            url,
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
            data={"grant_type": "client_credentials"}
        )
        response.raise_for_status()
        return response.json()["access_token"]
    except requests.RequestException:
        logger.exception("Access Token Fehler.")
        raise

def create_payment(title, user_id):
    access_token = get_access_token()
    url = f"https://api-m.{PAYPAL_MODE}.paypal.com/v2/checkout/orders"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"{user_id}-{title}",
            "amount": {"currency_code": "EUR", "value": "0.99"},
            "description": title
        }],
        "application_context": {
            "brand_name": "Geschichtenkiosk",
            "user_action": "PAY_NOW"
        }
    }
    response = requests.post(url, json=body, headers=headers)
    response.raise_for_status()
    data = response.json()
    return data["id"], next(link["href"] for link in data["links"] if link["rel"] == "approve")

def check_payment(order_id):
    access_token = get_access_token()
    url = f"https://api-m.{PAYPAL_MODE}.paypal.com/v2/checkout/orders/{order_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("status") in ["COMPLETED", "APPROVED"]
    except requests.RequestException:
        logger.exception("Zahlungsprüfung fehlgeschlagen.")
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

# --- Telegram Bot Handlers ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = InlineKeyboardMarkup()
    for title in PDF_FILES:
        markup.add(InlineKeyboardButton(text=title, callback_data=f"buy_{title}"))
    bot.send_message(message.chat.id,
                     "📚 Willkommen im Geschichtenkiosk! Wähle eine Geschichte (0,99€):",
                     reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_purchase(call):
    chat_id = call.message.chat.id
    title = call.data.replace("buy_", "")
    try:
        order_id, approval_url = create_payment(title, chat_id)
        user_state[chat_id] = {"title": title, "order_id": order_id}
        bot.send_message(chat_id,
                         f"✅ *{title}* ausgewählt.\nBezahl hier: {approval_url}\n\nSende danach deine *Order-ID*, um die Geschichte zu erhalten.",
                         parse_mode="Markdown")
    except Exception:
        bot.send_message(chat_id, "❌ Fehler beim Erstellen der Zahlung.")

@bot.message_handler(func=lambda m: m.text and m.text.startswith("ORDER-"))
def handle_order_id(message):
    chat_id = message.chat.id
    order_id = message.text.strip()

    if chat_id not in user_state or user_state[chat_id].get("order_id") != order_id:
        return bot.send_message(chat_id, "⚠️ Bitte zuerst eine Geschichte auswählen oder gültige Order-ID angeben.")

    if check_payment(order_id):
        file_id = PDF_FILES.get(user_state[chat_id]["title"])
        pdf = download_pdf(file_id)
        if pdf:
            bot.send_document(chat_id, pdf, visible_file_name=f"{user_state[chat_id]['title']}.pdf")
            bot.send_message(chat_id, "🎉 Danke für deinen Kauf! "
                                      "Mit deiner Unterstützung hilfst du unseren kleinen Geschichtenzauberern, "
                                      "ihre Träume zu leben und unsere Familie auf kleine Abenteuer zu schicken. "
                                      "Wir freuen uns riesig, dich bald mit neuen spannenden Geschichten überraschen zu dürfen! 📚✨\n"
                                      "Viel Spaß beim Lesen! 🎉")
        else:
            bot.send_message(chat_id, "❌ Fehler beim Herunterladen des PDFs.")
    else:
        bot.send_message(chat_id, "❌ Zahlung noch nicht abgeschlossen oder ungültig.")

# --- Bot starten ---
if __name__ == "__main__":
    logger.info("Bot wird gestartet (infinity_polling)...")
    bot.infinity_polling()
