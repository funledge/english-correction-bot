from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import openai

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
                {"role": "system", "content": "あなたはフレンドリーで丁寧な英語の先生です。以下の英文を3つのパートに分けて添削してください。\n\n1. 「✏️原文」というラベルを見出しにして、1行下にその英文を記載してください\n2. 「✅添削後の英文」というラベルを見出しにして、1行下に正しい文を記載してください\n3. 「💡間違いの理由やアドバイス」というラベルを見出しにして、1行下にやさしいアドバイスを書いてください（敬語で、フレンドリーで、中学生にもわかるように。絵文字は1〜2個だけ使ってください）\n\n各ラベルは**必ず**表示し、省略しないでください。"},
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
