import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set.")

JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
report_date = now.strftime("%Y年%-m月%-d日")


def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def fetch_news(query, limit=5):
    """Fetch a small amount of current public news context without a paid search API."""
    params = urllib.parse.urlencode({
        "q": f"{query} when:7d",
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    })
    url = f"https://news.google.com/rss/search?{params}"
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            root = ET.fromstring(response.read())

        items = []
        for item in root.findall("./channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            source = item.find("source")
            source_name = (source.text or "").strip() if source is not None else ""
            if title:
                items.append(f"- {title} | {source_name} | {pub_date} | {link}")
        return "\n".join(items) or "(No recent items found.)"
    except Exception as e:
        print(f"News context fetch failed for {query}: {e}", flush=True)
        return "(News context unavailable.)"


current_html = read_file("index.html")
if not current_html:
    raise RuntimeError("index.html was not found.")

try:
    previous_html = os.popen("git show HEAD~1:index.html 2>/dev/null").read()
except Exception:
    previous_html = ""

news_context = "\n\n".join([
    "### ChatGPT / OpenAI\n" + fetch_news("OpenAI ChatGPT"),
    "### Gemini / Google\n" + fetch_news("Google Gemini AI"),
    "### Claude / Anthropic\n" + fetch_news("Anthropic Claude AI"),
    "### Microsoft Copilot\n" + fetch_news("Microsoft Copilot AI"),
])

prompt = f"""
あなたは企業の内部監査・IT統制・AIガバナンスを担当する専門家です。

「主要AIアプリ アップデートまとめ」という週刊レポートを作成してください。
対象サービスは ChatGPT / OpenAI、Gemini / Google、Claude / Anthropic、Microsoft Copilot です。

目的は単なるAIニュースまとめではなく、内部監査担当者が「何を確認すべきか」を把握できる実務向けレポートです。

重要ルール:
1. 下記の「直近7日間の公開ニュース候補」を最新情報の手掛かりとして使ってください。
2. 公式情報・一次情報を最優先してください。ニュース候補だけで断定せず、公式情報が確認できない事項は「現時点で公式情報を確認できず」と明記してください。
3. 事実と分析・意見を明確に分けてください。
4. 存在を確認できないモデル名・機能名・料金・提供条件などを推測しないでください。
5. 前回レポートとの差分を重視してください。
6. 各重要アップデートを、新規・変更・継続・終了の可能な範囲で判定してください。
7. 各重要アップデートに重要度を付けてください。★★★ 重要 / ★★☆ 注目 / ★☆☆ 参考
8. 情報源リンクは、ニュース候補に含まれるURLや、確実に存在すると判断できる公式ページだけを使ってください。URLを創作しないでください。

重点項目:
・新モデル ・モデル更新 ・モデル廃止 ・新機能 ・機能変更
・無料プラン変更 ・有料プラン変更 ・Enterprise機能 ・API
・セキュリティ ・管理者機能 ・AIエージェント ・スケジュール ・自動化
・Google Workspace ・Microsoft 365 ・Android ・iOS ・AIガバナンス

内部監査への示唆では、以下を具体的に整理してください。
・AIガバナンス ・IT全般統制 ・変更管理 ・アクセス管理 ・ログ管理
・情報セキュリティ ・AI利用ルール ・AI出力の品質管理 ・監査証跡 ・業務へのAI導入

レポート構成:
1. 今週の重要アップデートTOP5
2. ChatGPT / OpenAI
3. Gemini / Google
4. Claude / Anthropic
5. Microsoft Copilot
6. 内部監査への示唆
7. 今後ウォッチすべき事項
8. 情報源

TOP5は内部監査・IT統制・AIガバナンスへの影響が大きいものを優先してください。

HTML要件:
- 完全なHTML文書として出力
- 外部CSS・JavaScriptに依存しない
- CSSはHTML内部に記述
- スマートフォンで読みやすいレスポンシブデザイン
- 情報源にはクリック可能なリンクを付ける
- HTML以外の説明文は出力しない
- 最後に必ず「このレポートは公開情報に基づく情報整理であり、監査判断そのものを代替するものではありません。」を入れる

今回の基準日: {report_date}
レポート本文の基準日は必ずこの日付を使用し、過去HTMLの日付を再利用しないでください。

直近7日間の公開ニュース候補:
{news_context}

前回レポート:
{previous_html}

現在のHTML:
{current_html}
"""

# Gemini 3.1 Flash-Lite is a current stable model with Free Tier input/output.
# Google Search grounding is not included here because it is not available in the Free Tier.
# Instead, the workflow supplies fresh Google News RSS context without using a paid search API.
model = "gemini-3.1-flash-lite"
url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

payload = {
    "contents": [{"parts": [{"text": prompt}]}]
}

request = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "x-goog-api-key": API_KEY,
        "Content-Type": "application/json"
    },
    method="POST"
)

print("Calling Gemini API...", flush=True)

max_attempts = 5
result = None

for attempt in range(1, max_attempts + 1):
    try:
        print(f"Gemini API attempt {attempt}/{max_attempts}...", flush=True)
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
        print(f"Gemini API request succeeded on attempt {attempt}/{max_attempts}.", flush=True)
        break
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass

        reason = ""
        try:
            error_json = json.loads(body)
            reason = error_json.get("error", {}).get("status", "") or error_json.get("error", {}).get("message", "")
        except (TypeError, ValueError):
            reason = body[:500]

        print(f"Gemini API HTTP {e.code}: {reason}", flush=True)

        if e.code != 429 or attempt == max_attempts:
            raise RuntimeError(f"Gemini API request failed: HTTP {e.code}: {reason}")

        wait_seconds = min(60 * (2 ** (attempt - 1)), 300)
        print(f"Retrying in {wait_seconds} seconds...", flush=True)
        time.sleep(wait_seconds)

if result is None:
    raise RuntimeError("Gemini API returned no result.")

try:
    output = "".join(
        part.get("text", "")
        for part in result["candidates"][0]["content"]["parts"]
        if isinstance(part, dict)
    ).strip()
except (KeyError, IndexError, TypeError) as e:
    raise RuntimeError("Gemini API response did not contain generated text: " + str(e))

# Gemini may occasionally wrap HTML in a Markdown code fence.
if output.startswith("```html"):
    output = output[7:]
    if output.endswith("```"):
        output = output[:-3]
elif output.startswith("```"):
    output = output[3:]
    if output.endswith("```"):
        output = output[:-3]

output = output.strip()

if not output.lower().startswith("<!doctype html") and "<html" not in output.lower():
    raise RuntimeError("Gemini output was not valid HTML.")

with open("index.html", "w", encoding="utf-8") as f:
    f.write(output)

print(f"Report generated successfully for {report_date}.", flush=True)
