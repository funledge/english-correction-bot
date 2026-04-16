from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import openai

import gspread
from google.oauth2.service_account import Credentials
import json
import random

app = Flask(__name__)

def get_users_and_topic():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # Renderの環境変数から認証情報を取得
    credentials_info = json.loads(os.environ.get("GOOGLE_CREDENTIALS_JSON"))
    creds = Credentials.from_service_account_info(credentials_info, scopes=scope)
    client = gspread.authorize(creds)

    # スプレッドシートを開く（名前をあなたのシート名に合わせて！）
    sheet = client.open("添削Botユーザー")

    # ユーザーID取得（A列）
    user_sheet = sheet.worksheet("users")
    user_ids = user_sheet.col_values(1)[1:]  # ヘッダー除く

    # お題リスト取得（A列）
    topic_sheet = sheet.worksheet("topics")
    topics = topic_sheet.col_values(1)[1:]
    selected_topic = random.choice(topics)

    return user_ids, selected_topic


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
    print("handle_message triggered")

    try:
        user_id = event.source.user_id
        print(f"user_id: {user_id}")
    except Exception as e:
        print(f"user_id error: {e}")　　
        
user_id = event.source.user_id
save_user_id(user_id)
user_input = event.message.text

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "あなたはフレンドリーで丁寧な英語の先生です。以下の英文を3つのパートに分けて添削してください。\n\n1. 「✏️原文」というラベルを見出しにして、1行下にその英文を記載してください\n2. 「✅添削後の英文」というラベルを見出しにして、1行下に正しい文を記載してください\n3. 「💡間違いの理由やアドバイス」というラベルを見出しにして、1行下にやさしいアドバイスを書いてください\n\n各ラベルは必ず表示し、省略しないでください。"
                },
                {
                    "role": "user",
                    "content": user_input
                }
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
