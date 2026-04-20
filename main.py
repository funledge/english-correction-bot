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

from datetime import datetime

@app.route("/health")
def health():
    print(f"[{datetime.now()}] health ping received")
    return "ok", 200

# 環境変数読み込み
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# OpenAIクライアント初期化
client = openai.OpenAI(api_key=OPENAI_API_KEY)

SPREADSHEET_NAME = "添削Botユーザー"
OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_MODE = "correction"
DICTIONARY_MODE = "dictionary"
DICTIONARY_TRIGGER = "辞書"
BUSY_MESSAGE = "少し混み合っているみたい。\n少し時間をあけて、もう一度送ってみてね！"
DICTIONARY_FREE_LIMIT = 5
DICTIONARY_LIMIT_MESSAGE = "無料で使えるのは5回までです😊\nProプランにすると無制限に使えるよ！\nURL"
DICTIONARY_GUIDE_MESSAGE = (
    "📘 辞書機能です！\n"
    "調べたい単語や熟語を送ってください😊\n"
    "英語でも日本語でもOKです！\n"
    "例：\n"
    "・take off\n"
    "・やり直す\n"
    "・actually"
)


def get_gspread_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    credentials_info = json.loads(os.environ.get("GOOGLE_CREDENTIALS_JSON"))
    creds = Credentials.from_service_account_info(credentials_info, scopes=scope)
    return gspread.authorize(creds)


def get_spreadsheet():
    client_gspread = get_gspread_client()
    return client_gspread.open(SPREADSHEET_NAME)


def normalize_header(header):
    return header.strip().lower().replace(" ", "_")


def get_header_index(headers, target_name):
    normalized_target = normalize_header(target_name)

    for index, header in enumerate(headers, start=1):
        if normalize_header(header) == normalized_target:
            return index

    return None


def ensure_worksheet(sheet, worksheet_name, headers, rows=1000, cols=10):
    try:
        worksheet = sheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=worksheet_name, rows=rows, cols=cols)
        worksheet.append_row(headers)
        return worksheet

    first_row = worksheet.row_values(1)
    if not first_row:
        worksheet.append_row(headers)
        return worksheet

    for col_index, header in enumerate(headers, start=1):
        if len(first_row) < col_index or not first_row[col_index - 1].strip():
            worksheet.update_cell(1, col_index, header)

    return worksheet


def get_users_and_topic():
    sheet = get_spreadsheet()

    user_sheet = ensure_worksheet(sheet, "users", ["user_id", "paid_plan"])
    user_ids = user_sheet.col_values(1)[1:]

    topic_sheet = ensure_worksheet(sheet, "topics", ["topic"])
    topics = topic_sheet.col_values(1)[1:]
    selected_topic = random.choice(topics) if topics else "今日は英語で1文書いてみよう！"

    return user_ids, selected_topic


def save_user_id(user_id):
    sheet = get_spreadsheet()
    user_sheet = ensure_worksheet(sheet, "users", ["user_id", "paid_plan"])

    records = user_sheet.get_all_values()
    headers = records[0] if records else ["user_id", "paid_plan"]
    user_id_col = get_header_index(headers, "user_id") or 1
    paid_plan_col = get_header_index(headers, "paid_plan") or 2

    for row in records[1:]:
        if len(row) >= user_id_col and row[user_id_col - 1] == user_id:
            return

    row_length = max(user_id_col, paid_plan_col)
    new_row = [""] * row_length
    new_row[user_id_col - 1] = user_id
    user_sheet.append_row(new_row)


def check_and_update_usage(user_id):
    sheet = get_spreadsheet()
    usage_sheet = ensure_worksheet(sheet, "usage", ["user_id", "date", "count"])

    today = datetime.now().strftime("%Y-%m-%d")
    records = usage_sheet.get_all_values()

    for i, row in enumerate(records[1:], start=2):
        if len(row) < 3:
            continue

        row_user_id = row[0]
        row_date = row[1]

        try:
            row_count = int(row[2])
        except ValueError:
            row_count = 0

        if row_user_id == user_id and row_date == today:
            if row_count >= 10:
                return False

            usage_sheet.update_cell(i, 3, row_count + 1)
            return True

    usage_sheet.append_row([user_id, today, 1])
    return True


def check_and_update_dictionary_usage(user_id):
    sheet = get_spreadsheet()
    usage_sheet = ensure_worksheet(sheet, "dictionary_usage", ["user_id", "date", "count"])

    today = datetime.now().strftime("%Y-%m-%d")
    records = usage_sheet.get_all_values()

    for i, row in enumerate(records[1:], start=2):
        if len(row) < 3:
            continue

        row_user_id = row[0]
        row_date = row[1]

        try:
            row_count = int(row[2])
        except ValueError:
            row_count = 0

        if row_user_id == user_id and row_date == today:
            if row_count >= DICTIONARY_FREE_LIMIT:
                return False

            usage_sheet.update_cell(i, 3, row_count + 1)
            return True

    usage_sheet.append_row([user_id, today, 1])
    return True


def get_user_paid_plan(user_id):
    sheet = get_spreadsheet()
    user_sheet = ensure_worksheet(sheet, "users", ["user_id", "paid_plan"])
    records = user_sheet.get_all_values()

    if not records:
        return ""

    headers = records[0]
    user_id_col = get_header_index(headers, "user_id") or 1
    paid_plan_col = get_header_index(headers, "paid_plan")

    if not paid_plan_col:
        return ""

    for row in records[1:]:
        if len(row) >= user_id_col and row[user_id_col - 1] == user_id:
            if len(row) >= paid_plan_col:
                return row[paid_plan_col - 1].strip().lower()
            return ""

    return ""


def can_use_dictionary_unlimited(user_id):
    return get_user_paid_plan(user_id) == DICTIONARY_MODE


def get_user_mode(user_id):
    sheet = get_spreadsheet()
    mode_sheet = ensure_worksheet(sheet, "user_modes", ["user_id", "mode", "updated_at"])
    records = mode_sheet.get_all_values()

    if not records:
        return DEFAULT_MODE

    headers = records[0]
    user_id_col = get_header_index(headers, "user_id") or 1
    mode_col = get_header_index(headers, "mode") or 2

    for row in records[1:]:
        if len(row) >= user_id_col and row[user_id_col - 1] == user_id:
            if len(row) >= mode_col and row[mode_col - 1].strip():
                return row[mode_col - 1].strip()
            return DEFAULT_MODE

    return DEFAULT_MODE


def set_user_mode(user_id, mode):
    sheet = get_spreadsheet()
    mode_sheet = ensure_worksheet(sheet, "user_modes", ["user_id", "mode", "updated_at"])
    records = mode_sheet.get_all_values()
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not records:
        mode_sheet.append_row([user_id, mode, now_text])
        return

    headers = records[0]
    user_id_col = get_header_index(headers, "user_id") or 1
    mode_col = get_header_index(headers, "mode") or 2
    updated_at_col = get_header_index(headers, "updated_at") or 3

    for row_index, row in enumerate(records[1:], start=2):
        if len(row) >= user_id_col and row[user_id_col - 1] == user_id:
            mode_sheet.update_cell(row_index, mode_col, mode)
            mode_sheet.update_cell(row_index, updated_at_col, now_text)
            return

    row_length = max(user_id_col, mode_col, updated_at_col)
    new_row = [""] * row_length
    new_row[user_id_col - 1] = user_id
    new_row[mode_col - 1] = mode
    new_row[updated_at_col - 1] = now_text
    mode_sheet.append_row(new_row)


def send_text(user_id, text):
    line_bot_api.push_message(
        user_id,
        TextSendMessage(text=text)
    )


def build_correction_reply(user_input):
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
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
        ],
        temperature=0.4
    )

    return response.choices[0].message.content.strip()


def build_dictionary_reply(user_input):
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "あなたは親切な英日・日英辞書アシスタントです。"
                    "入力が英語なら日本語に、日本語なら英語に翻訳してください。"
                    "単語、熟語、短文、文章のどれにも対応してください。\n\n"
                    "特に重要なルール:\n"
                    "・入力が日本語のときは、「🔤単語」には必ず英語の訳語だけを書く\n"
                    "・入力が日本語のときは、日本語の言い換えや説明を書かない\n"
                    "・例えば「健康」なら、「健康的」ではなく英語の見出し語を出す\n"
                    "・入力が英語のときは、「🔤単語」には英語の元表現を書く\n"
                    "・品詞は見出し語に合わせて自然なものを書く\n"
                    "・例文は必ず英語の例文を1つ書き、その次の行に日本語訳を丸かっこ付きで書く\n"
                    "・単語の意味は、翻訳先の言語でわかりやすく簡潔に書く\n"
                    "・文章入力なら、「🔤単語」には文章全体の自然な翻訳を書く\n"
                    "・必ず次の4項目をこの順番、この見出しで返す\n\n"
                    "🔤単語\n"
                    "📝意味\n"
                    "🧩品詞\n"
                    "💬例文"
                )
            },
            {
                "role": "user",
                "content": user_input
            }
        ],
        temperature=0.2
    )

    return response.choices[0].message.content.strip()


@app.route("/send-topic", methods=["POST"])
def send_topic():
    try:
        user_ids, selected_topic = get_users_and_topic()

        for user_id in user_ids:
            if not user_id.strip():
                continue

            send_text(user_id, f"📘 今日のお題\n\n{selected_topic}")

        return "OK"

    except Exception as e:
        print(f"send_topic error: {e}", flush=True)
        return f"Error: {str(e)}", 500


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    print("handle_message triggered", flush=True)

    user_id = None

    try:
        user_id = event.source.user_id
        user_input = event.message.text.strip()
        print(f"user_id: {user_id}", flush=True)

        save_user_id(user_id)
        current_mode = get_user_mode(user_id)

        if user_input == DICTIONARY_TRIGGER:
            is_dictionary_paid_user = can_use_dictionary_unlimited(user_id)

            if not is_dictionary_paid_user:
                can_use_free_dictionary = check_and_update_dictionary_usage(user_id)

                if not can_use_free_dictionary:
                    send_text(user_id, DICTIONARY_LIMIT_MESSAGE)
                    return

            set_user_mode(user_id, DICTIONARY_MODE)
            send_text(user_id, DICTIONARY_GUIDE_MESSAGE)
            return

        if current_mode == DICTIONARY_MODE:
            try:
                reply_text = build_dictionary_reply(user_input)
            except Exception as e:
                print(f"dictionary error: {e}", flush=True)
                reply_text = BUSY_MESSAGE
            finally:
                set_user_mode(user_id, DEFAULT_MODE)

            send_text(user_id, reply_text)
            return

        can_use = check_and_update_usage(user_id)

        if not can_use:
            reply_text = (
                "本日の無料添削は10回までです😊\n\n"
                "もっと使いたい方は、有料プランをご利用ください！"
            )
            send_text(user_id, reply_text)
            return

        try:
            reply_text = build_correction_reply(user_input)
        except Exception as e:
            print(f"correction error: {e}", flush=True)
            reply_text = BUSY_MESSAGE

        send_text(user_id, reply_text)

    except Exception as e:
        print(f"handle_message error: {e}", flush=True)

        if user_id:
            try:
                if get_user_mode(user_id) == DICTIONARY_MODE:
                    set_user_mode(user_id, DEFAULT_MODE)
            except Exception as mode_error:
                print(f"mode reset error: {mode_error}", flush=True)

            try:
                send_text(user_id, BUSY_MESSAGE)
            except Exception as push_error:
                print(f"push error: {push_error}", flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
