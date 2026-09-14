import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from html import escape

API_KEY = os.environ.get("OPENAI_API_KEY")

if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set.")

JST = timezone(timedelta(hours=9))

now = datetime.now(JST)
report_date = now.strftime("%Y年%-m月%-d日")

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""

current_html = read_file("index.html")

if not current_html:
    raise RuntimeError("index.html was not found.")

previous_html = ""

try:
    previous_html = os.popen(
        "git show HEAD~1:index.html 2>/dev/null"
    ).read()
except Exception:
    previous_html = ""

prompt = f"""
あなたは企業の内部監査・IT統制・AIガバナンスを担当する専門家です。

以下の情報をもとに、
「主要AIアプリ アップデートまとめ」
という週刊レポートを作成してください。

対象サービス：
- ChatGPT / OpenAI
- Gemini / Google
- Claude / Anthropic
- Microsoft Copilot

目的：
単なるAIニュースまとめではなく、
内部監査担当者が「何を確認すべきか」を把握できる
実務向けのレポートにしてください。

【重要なルール】
1. 事実と分析・意見を明確に分ける。
2. 存在を確認できないモデル名・機能名・料金・提供条件などを推測しない。
3. 公式情報を最優先する。
4. 必要に応じてWeb検索を利用し、可能な限り一次情報を確認する。
5. 確認できない情報は、「現時点で公式情報を確認できず」と明記する。
6. 前回レポートとの差分を重視する。
7. 各重要アップデートについて、新規・変更・継続・終了を可能な範囲で判定する。
8. 各重要アップデートに重要度を付ける。★★★ 重要 / ★★☆ 注目 / ★☆☆ 参考

【重点的に見る項目】
・新モデル ・モデル更新 ・モデル廃止 ・新機能 ・機能変更
・無料プラン変更 ・有料プラン変更 ・Enterprise機能 ・API
・セキュリティ ・管理者機能 ・AIエージェント ・スケジュール ・自動化
・Google Workspace ・Microsoft 365 ・Android ・iOS ・AIガバナンス

【内部監査への示唆】
以下の観点から、「監査・内部統制上、何を確認すべきか」を具体的に整理してください。
・AIガバナンス ・IT全般統制 ・変更管理 ・アクセス管理 ・ログ管理
・情報セキュリティ ・AI利用ルール ・AI出力の品質管理 ・監査証跡 ・業務へのAI導入

単なる「便利になった」という説明ではなく、「企業がAIを利用する場合、内部監査として何を確認すべきか」を優先してください。

【レポート構成】
1. 今週の重要アップデートTOP5
2. ChatGPT / OpenAI
3. Gemini / Google
4. Claude / Anthropic
5. Microsoft Copilot
6. 内部監査への示唆
7. 今後ウォッチすべき事項
8. 情報源

【TOP5】
内部監査・IT統制・AIガバナンスへの影響が大きいものを優先してください。

【HTML】
完全なHTML文書として出力してください。
外部CSS・JavaScriptには依存せず、CSSはHTML内部に記述してください。
スマートフォンでも読みやすいレスポンシブデザインにしてください。
情報源にはクリック可能なリンクを付けてください。
HTML以外の説明文は出力しないでください。
最後に必ず、「このレポートは公開情報に基づく情報整理であり、監査判断そのものを代替するものではありません。」という注意書きを入れてください。

【今回の基準日】
{report_date}

レポート本文に記載する「基準日」は、必ず上記の今回の基準日を使用してください。
過去のHTMLに記載されている基準日を今回の基準日として再利用しないでください。

【今回の情報】
{current_html}

【前回のレポート】
{previous_html}
"""

payload = {
    "model": "gpt-5.6-luna",
    "tools": [{"type": "web_search"}],
    "input": prompt
}

request = urllib.request.Request(
    "https://api.openai.com/v1/responses",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": "Bearer " + API_KEY,
        "Content-Type": "application/json"
    },
    method="POST"
)

print("Calling OpenAI API...", flush=True)

max_attempts = 5
retryable_status_codes = {429, 500, 502, 503, 504, 520}
api_timeout = 120
max_retry_after = 300

try:
    result = None

    for attempt in range(1, max_attempts + 1):
        try:
            print(f"OpenAI API attempt {attempt}/{max_attempts}...", flush=True)
            with urllib.request.urlopen(request, timeout=api_timeout) as response:
                result = json.loads(response.read().decode("utf-8"))

            print(f"OpenAI API request succeeded on attempt {attempt}/{max_attempts}.", flush=True)
            break

        except urllib.error.HTTPError as e:
            response_body = ""
            try:
                response_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            if e.code not in retryable_status_codes or attempt == max_attempts:
                raise

            retry_after = e.headers.get("Retry-After")
            if retry_after:
                try:
                    server_wait = max(1, int(float(retry_after)))
                except (TypeError, ValueError):
                    server_wait = 30 * (2 ** (attempt - 1))
            else:
                server_wait = 30 * (2 ** (attempt - 1))

            wait_seconds = min(server_wait, max_retry_after)
            if server_wait > max_retry_after:
                print(
                    f"HTTP {e.code} requested Retry-After={server_wait}s; "
                    f"capping wait at {max_retry_after}s.",
                    flush=True
                )

            reason = ""
            try:
                error_json = json.loads(response_body)
                reason = error_json.get("error", {}).get("code", "") or error_json.get("error", {}).get("type", "")
            except (TypeError, ValueError, AttributeError):
                pass

            if reason:
                print(f"OpenAI API error detail: {reason}", flush=True)

            print(
                f"OpenAI API returned HTTP {e.code}. "
                f"Retrying in {wait_seconds} seconds "
                f"(next attempt {attempt + 1}/{max_attempts})...",
                flush=True
            )
            time.sleep(wait_seconds)

    if result is None:
        raise RuntimeError("OpenAI API request returned no result.")

except Exception as e:
    raise RuntimeError("OpenAI API request failed: " + str(e))

output = ""

for item in result.get("output", []):
    if item.get("type") != "message":
        continue
    for content in item.get("content", []):
        if content.get("type") == "output_text":
            output += content.get("text", "")

output = output.strip()
