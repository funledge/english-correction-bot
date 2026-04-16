from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import openai
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import random

app = Flask(__name__)

# 環境変数読み込み
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# OpenAIクライアント初期化
client = openai.OpenAI(api_key=OPENAI_API_KEY)


def get_gspread_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    credentials_info = json.loads(os.environ.get("GOOGLE_CREDENTIALS_JSON"))
    creds = Credentials.from_service_account_info(credentials_info, scopes=scope)
    return gspread.authorize(creds)


def get_users_and_topic():
    client_gspread = get_gspread_client()

    sheet = client_gspread.open("添削Botユーザー")

    # usersシートからuserId取得
    user_sheet = sheet.worksheet("users")
    user_ids = user_sheet.col_values(1)[1:]  # ヘッダー除く

    # topicsシートからお題取得
    topic_sheet = sheet.worksheet("topics")
    topics = topic_sheet.col_values(1)[1:]  # ヘッダー除く
    selected_topic = random.choice(topics)

    return user_ids, selected_topic


def save_user_id(user_id):
    client_gspread = get_gspread_client()

    sheet = client_gspread.open("添削Botユーザー")
    user_sheet = sheet.worksheet("users")

    existing_users = user_sheet.col_values(1)

    # まだ登録されていないuserIdだけ追加
    if user_id not in existing_users:
        user_sheet.append_row([user_id])


def check_and_update_usage(user_id):
    client_gspread = get_gspread_client()

    sheet = client_gspread.open("添削Botユーザー")
    usage_sheet = sheet.worksheet("usage")

    today = datetime.now().strftime("%Y-%m-%d")
    records = usage_sheet.get_all_values()

    # 既存データを探す
    for i, row in enumerate(records[1:], start=2):
        row_user_id = row[0]
        row_date = row[1]
        row_count = int(row[2])

        if row_user_id == user_id and row_date == today:
            if row_count >= 10:
                return False

            usage_sheet.update_cell(i, 3, row_count + 1)
            return True

    # 今日初めて使う場合
    usage_sheet.append_row([user_id, today, 1])
    return True


@app.route("/send-topic", methods=['POST'])
def send_topic():
    try:
        user_ids, selected_topic = get_users_and_topic()

        for user_id in user_ids:
            if not user_id.strip():
                continue

            line_bot_api.push_message(
                user_id,
                TextSendMessage(text=f"📘 今日のお題\n\n{selected_topic}")
            )

        return 'OK'

    except Exception as e:
        print(f"send_topic error: {e}", flush=True)
        return f"Error: {str(e)}", 500


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
    print("handle_message triggered", flush=True)

    try:
        user_id = event.source.user_id
        print(f"user_id: {user_id}", flush=True)

        save_user_id(user_id)

        can_use = check_and_update_usage(user_id)

        if not can_use:
            reply_text = (
                "本日の無料添削は10回までです😊\n\n"
                "もっと使いたい方は、有料プランをご利用ください！"
            )

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
            return

    except Exception as e:
        print(f"user_id error: {e}", flush=True)

    user_input = event.message.text

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "あなたはフレンドリーで丁寧な英語の先生です。"
                        "以下の英文を3つのパートに分けて添削してください。\n\n"
                        "1. 「✏️原文」というラベルを見出しにして、1行下にその英文を記載してください\n"
                        "2. 「✅添削後の英文」というラベルを見出しにして、1行下に正しい文を記載してください\n"
                        "3. 「💡間違いの理由やアドバイス」というラベルを見出しにして、"
                        "1行下にやさしいアドバイスを書いてください\n\n"
                        "各ラベルは必ず表示し、省略しないでください。"
                    )
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
