import io
import logging
import requests
import config 
from flask import Flask, request
from telebot import TeleBot, types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from config import BOT_TOKEN, PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_MODE, WEBHOOK_URL

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Flask & Bot Setup ---
app = Flask(__name__)
bot = TeleBot(BOT_TOKEN)
user_state = {}

# --- Google Drive Setup ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

# --- PDF-Mapping ---
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

# ------------------ PAYPAL ------------------ #
def get_access_token() -> str:
    url = f"https://api-m.{'paypal' if PAYPAL_MODE == 'live' else 'sandbox'}.paypal.com/v1/oauth2/token"
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
    url = f"https://api-m.{'paypal' if PAYPAL_MODE == 'live' else 'sandbox'}.paypal.com/v2/checkout/orders"
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
            "return_url": f"{WEBHOOK_URL}/success",
            "cancel_url": f"{WEBHOOK_URL}/cancel",
            "user_action": "PAY_NOW"
        } 
    }
    try:
        response = requests.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        payment_id = data["id"]
        approval_url = next(link["href"] for link in data["links"] if link["rel"] == "approve")
        logger.info(f"Zahlung erstellt: {payment_id}")
        return payment_id, approval_url
    except requests.RequestException:
        logger.exception("Fehler beim Erstellen der Zahlung.")
        raise

def check_payment(order_id: str) -> bool:
    access_token = get_access_token()
    url = f"https://api-m.{'paypal' if PAYPAL_MODE == 'live' else 'sandbox'}.paypal.com/v2/checkout/orders/{order_id}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("status") in ["COMPLETED", "APPROVED"]
    except requests.RequestException:
        logger.exception("Fehler beim Überprüfen der Bestellung.")
        return False

# ------------------ DRIVE ------------------ #

def download_pdf(file_id: str) -> io.BytesIO | None:
    try:
        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        return fh
    except Exception as e:
        logger.exception("Fehler beim PDF-Download.")
        return None

# ------------------ TELEGRAM ------------------ #

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = InlineKeyboardMarkup()
    for title in PDF_FILES:
        markup.add(InlineKeyboardButton(text=title, callback_data=f"buy_{title}"))
    bot.send_message(message.chat.id,
                     "Willkommen im Geschichtenkiosk! 📚\nWähle eine Geschichte zum Kauf (0,99€):",
                     reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_purchase(call):
    chat_id = call.message.chat.id
    title = call.data.replace("buy_", "")
    try:
        order_id, approval_url = create_payment(title, chat_id)
        user_state[chat_id] = {"title": title, "order_id": order_id, "payment_completed": False}
        bot.send_message(chat_id,
                         f"✅ *{title}* gewählt.\nBezahlen kannst du hier: {approval_url}\n\nSende danach die *Order-ID*, um deine Geschichte zu erhalten.",
                         parse_mode="Markdown")
    except Exception:
        bot.send_message(chat_id, "❌ Fehler bei der Zahlung. Bitte versuche es später erneut.")

@bot.message_handler(func=lambda m: m.text and m.text.startswith("ORDER-"))
def handle_order_id(message):
    chat_id = message.chat.id
    order_id = message.text.strip()

    if chat_id not in user_state:
        return bot.send_message(chat_id, "Bitte zuerst eine Geschichte auswählen.")

    if user_state[chat_id].get("order_id") != order_id:
        return bot.send_message(chat_id, "⚠️ Diese Order-ID passt nicht zur vorherigen Bestellung.")

    if check_payment(order_id):
        file_id = PDF_FILES.get(user_state[chat_id]["title"])
        pdf = download_pdf(file_id)

        if pdf:
            bot.send_document(chat_id, pdf, visible_file_name=f"{user_state[chat_id]['title']}.pdf")
            thank_you_message = (
                "Danke für deinen Kauf!\n"
                "Mit deiner Unterstützung hilfst du unseren kleinen Geschichtenzauberern, "
                "ihre Träume zu leben und unsere Familie auf kleine Abenteuer zu schicken. "
                "Wir freuen uns riesig, dich bald mit neuen spannenden Geschichten überraschen zu dürfen! 📚✨\n"
                "Viel Spaß beim Lesen!"
            )
            bot.send_message(chat_id, thank_you_message)
        else:
            bot.send_message(chat_id, "PDF konnte nicht geladen werden.")
    else:
        bot.send_message(chat_id, "❌ Zahlung noch nicht abgeschlossen oder ungültig.")

# ------------------ FLASK (z. B. Webhook) ------------------ #

@app.route('/')
def index():
    return "Bot läuft."

@app.route('/success')
def payment_success():
    return "Zahlung erfolgreich. Du kannst zurück zum Telegram-Bot."

@app.route('/cancel')
def payment_cancel():
    return "Zahlung abgebrochen. Du kannst zurück zum Telegram-Bot."

@app.route('/webhook', methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return 'OK'

if __name__ == "__main__":
    import os
    # Setup webhook for Telegram (optional)
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL + '/webhook')
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
