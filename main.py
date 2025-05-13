from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import openai

import gspread
from google.oauth2.service_account import Credentials
import random

def get_users_and_topic():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file("credentials.json", scopes=scope)
    client = gspread.authorize(creds)

    sheet = client.open("添削Botユーザー")  # ← あなたのスプレッドシート名に合わせて！
    
    # ユーザーID取得
    user_sheet = sheet.worksheet("users")
    user_ids = user_sheet.col_values(1)[1:]  # A列（ヘッダー除く）

    # お題リスト取得
    topic_sheet = sheet.worksheet("topics")
    topics = topic_sheet.col_values(1)[1:]  # A列（ヘッダー除く）
    selected_topic = random.choice(topics)

    return user_ids, selected_topic

@app.route("/send-topic", methods=['POST'])
def send_topic():
    user_ids, selected_topic = get_users_and_topic()

    for user_id in user_ids:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=f"📘 今日のお題\n{selected_topic}")
        )
    return 'OK'


app = Flask(__name__)

# 環境変数読み込み
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# OpenAIクライアントの初期化（最新形式）
client = openai.OpenAI(api_key=OPENAI_API_KEY)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_input = event.message.text

    try:
        # ChatGPTに添削リクエスト
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "あなたは親切な英語教師です。以下の英文を3つのポイントに分けて添削してください。\n1. 原文\n2. 添削後の正しい文\n3. 間違いの理由やアドバイス（優しく！）\nフォーマットを守って、初心者にもわかりやすく伝えてください。"},
                {"role": "user", "content": user_input}
            ]
        )
        reply_text = response.choices[0].message.content.strip()
    except Exception as e:
        reply_text = f"エラーが発生しました：{str(e)}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
