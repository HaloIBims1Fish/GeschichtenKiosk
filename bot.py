#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Geschichtenkiosk – Zahlung via PayPal & PDF-Download per Direktlink
Autor: Fischi (2025)
"""

import io
import logging
import requests
from flask import Flask, request, jsonify
from telebot import TeleBot, types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_MODE, WEBHOOK_URL

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = TeleBot(BOT_TOKEN)
app = Flask(__name__)
bot.remove_webhook()
user_state = {}

# --- PDF-Dateien per Direktlink ---
PDF_FILES = {
    "Lilly und der Regenbogenschirm": "https://drive.google.com/uc?export=download&id=112CF9AOH8MbOZyZkgVN4UdlvZrjQdDhq",
    "Finns Flaschenpost aus dem Meer": "https://drive.google.com/uc?export=download&id=1nZH5ncjgEP6klYbhAJcGEiU5vH-ISD_U",
    "Die Abenteuer von Kalle, dem Keksdieb": "https://drive.google.com/uc?export=download&id=1MYIARCf0DFs0Gq1wdn-8fBMDYmSYYFxe",
    "Mira und die flüsternden Bücher": "https://drive.google.com/uc?export=download&id=1AF_vdS_m3YCaDmF1VO9HqUKsSgn75hOi",
    "Emil im Land der verlorenen Sachen": "https://drive.google.com/uc?export=download&id=1sVpY0FoHAcAOTbGnTeqx3birFrNTkrSW",
    "Der Zauberzoo hinter dem Schrank": "https://drive.google.com/uc?export=download&id=19COgUGIn4rUwX2yQfYi9FPBUEuoJE47w",
    "Nino und das Geheimnis der Sternenfreunde": "https://drive.google.com/uc?export=download&id=1E4OwMSoZRz4pBHwcU01YsOb6wxB5-zZN",
    "Die Wolkenfee und das Donnerwetter": "https://drive.google.com/uc?export=download&id=1Tv7IR0Q14jLhliHgP-VV91XJMv6T6l8X",
    "Tom und das fliegende Frühstücksei": "https://drive.google.com/uc?export=download&id=1Kmio4YjXdBPfkUPVtue3Ty9U11GyfTlP",
    "Die Uhr, die rückwärts lief": "https://drive.google.com/uc?export=download&id=1YADu1ttscox2yG67frZDD03ZeGB-VM5N",
    "Lotte und der Wunschstein": "https://drive.google.com/uc?export=download&id=1wV4JFepP5Mlk0NmIU9xPJDCOZKRd2h35",
    "Benni baut sich eine Rakete": "https://drive.google.com/uc?export=download&id=1tjbqnG2-H-xW0Ffj8lOmbcBckwfdHbb8",
    "Die Piratin mit der Zahnlücke": "https://drive.google.com/uc?export=download&id=16jkLPOIfUnEwMnKPRLiWJ0BzjFQwA0tO",
    "Paul und das Haustier aus dem All": "https://drive.google.com/uc?export=download&id=1KpEIh0d5raLLANJly_2fp8-1l67W37ot"
}

# --- PDF-Download über Direktlink ---
def download_pdf_from_link(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return io.BytesIO(response.content)
    except Exception:
        logger.exception("Download fehlgeschlagen.")
        return None

# --- PayPal ---
def get_access_token():
    url = f"https://api-m.{ 'paypal.com' if PAYPAL_MODE == 'live' else 'sandbox.paypal.com' }/v1/oauth2/token"
    try:
        response = requests.post(url, auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET), data={"grant_type": "client_credentials"})
        response.raise_for_status()
        return response.json()["access_token"]
    except requests.RequestException:
        logger.exception("Fehler beim Abrufen des PayPal Tokens.")
        raise

def create_payment(title, user_id):
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
    user_state[order_id] = {"chat_id": user_id, "title": title}
    return order_id, approval_url

def capture_payment(order_id):
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
        return True
    except requests.RequestException:
        logger.exception("Fehler beim Capturen der Zahlung.")
        return False

# --- Telegram Handler ---
@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.send_message(message.chat.id,
        "👋 Willkommen im *Geschichtenkiosk*!\n\n"
        "Unsere Kinder hatten die Idee, ein Sparkonto für Urlaubswünsche anzulegen. "
        "Mit deinem Kauf hilfst du dabei. 🙏\n\n"
        "📚 So funktioniert's:\n"
        "1️⃣ Geschichte auswählen\n"
        "2️⃣ Per PayPal (1,19 €) zahlen\n"
        "3️⃣ PDF wird direkt im Chat gesendet",
        parse_mode="Markdown")

    markup = InlineKeyboardMarkup()
    for title in PDF_FILES:
        markup.add(InlineKeyboardButton(text=title, callback_data=f"buy_{title}"))
    bot.send_message(message.chat.id, "Welche Geschichte möchtest du kaufen?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_purchase(call):
    chat_id = call.message.chat.id
    title = call.data.replace("buy_", "")
    try:
        order_id, approval_url = create_payment(title, chat_id)
        bot.send_message(chat_id,
            f"✅ *{title}* wurde ausgewählt.\n"
            f"Bitte bezahle sicher via PayPal:\n{approval_url}",
            parse_mode="Markdown")
    except Exception:
        bot.send_message(chat_id, "❌ Fehler beim Erstellen der Zahlung. Bitte später erneut versuchen.")

@app.route("/", methods=["POST"])
def telegram_webhook():
    update = types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return jsonify({"status": "ok"})

# --- PayPal Rückkehr ---
@app.route("/return")
def paypal_return():
    order_id = request.args.get("token")
    if not order_id or order_id not in user_state:
        return "❌ Ungültige Bestellung oder Session abgelaufen.", 400

    chat_id = user_state[order_id]["chat_id"]
    title = user_state[order_id]["title"]
    user_state.pop(order_id)

    if capture_payment(order_id):
        pdf = download_pdf_from_link(PDF_FILES[title])
        if pdf:
            bot.send_document(chat_id, pdf, visible_file_name=f"{title}.pdf")
            bot.send_message(chat_id, "🎉 Danke für deinen Kauf! Viel Spaß beim Lesen! 📖")
            return "✅ PDF erfolgreich gesendet."
        else:
            return "⚠️ PDF-Download fehlgeschlagen.", 500
    else:
        return "❌ Zahlung konnte nicht bestätigt werden.", 500

@app.route("/cancel")
def paypal_cancel():
    return "❌ Zahlung abgebrochen. Du kannst jederzeit neu starten."

@app.route("/", methods=["GET"])
def home():
    return "📡 Webhook aktiv!", 200

# --- Webhook setzen ---
if __name__ == "__main__":
    logger.info("🚀 Starte Bot...")
    bot.remove_webhook()
    success = bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    logger.info(f"🌐 Webhook gesetzt: {success}")
    app.run(host="0.0.0.0", port=5000)
