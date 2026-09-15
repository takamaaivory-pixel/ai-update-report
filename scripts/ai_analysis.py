import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set.")

JST = timezone(timedelta(hours=9))
report_date = datetime.now(JST).strftime("%Y年%-m月%-d日")
MODEL = "gemini-3.1-flash-lite"


def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def fetch_news(query, limit=6):
    params = urllib.parse.urlencode({
        "q": f"{query} when:7d",
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    })
    url = f"https://news.google.com/rss/search?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            root = ET.fromstring(response.read())
        items = []
        for item in root.findall("./channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            source = item.find("source")
            source_name = (source.text or "").strip() if source is not None else ""
            source_url = source.get("url", "") if source is not None else ""
            if title:
                items.append(f"- {title} | source={source_name} | source_url={source_url} | date={pub_date} | link={link}")
        return "\n".join(items) or "(No recent items found.)"
    except Exception as e:
        print(f"News context fetch failed for {query}: {e}", flush=True)
        return "(News context unavailable.)"


current_html = read_file("index.html")
if not current_html:
    raise RuntimeError("index.html was not found.")

previous_html = os.popen("git show HEAD~1:index.html 2>/dev/null").read()

news_context = "\n\n".join([
    "### OpenAI / official-domain candidates\n" + fetch_news("site:openai.com ChatGPT OpenAI"),
    "### Google / official-domain candidates\n" + fetch_news("site:blog.google Gemini Google AI"),
    "### Anthropic / official-domain candidates\n" + fetch_news("site:anthropic.com Claude Anthropic"),
    "### Microsoft / official-domain candidates\n" + fetch_news("site:techcommunity.microsoft.com Copilot Microsoft"),
    "### Broader corroborating news\n" + fetch_news("OpenAI ChatGPT OR Google Gemini OR Anthropic Claude OR Microsoft Copilot"),
])

prompt = f"""
あなたは企業の内部監査・IT統制・AIガバナンス担当者向けの週刊レポート編集者です。

基準日: {report_date}
対象: ChatGPT/OpenAI、Gemini/Google、Claude/Anthropic、Microsoft Copilot

最重要ルール:
- 事実を最優先し、推測・創作は禁止。
- 下記ニュース候補を材料にし、重要事項は可能な限り公式情報を優先する。
- 「source_url」が公式ドメインの候補にある場合は、それを一次情報として扱ってよい。
- 公式ドメインで確認できない主張は断定せず、「公式情報で確認できず」と明記する。
- モデル名、製品名、料金、提供地域、提供時期、機能、仕様を想像で補完しない。
- 情報源URLを新規に創作しない。下記候補に存在するURLだけを使用する。
- Google Newsのredirect URLしかない場合は、それを情報源リンクとして使ってよいが、本文では「ニュース候補」として扱う。
- 事実と監査上の分析を明確に分ける。
- 前回レポートとの差分を重視し、変化がない項目は無理にニュース化しない。

特に重視:
新モデル/更新/廃止、新機能、料金・無料枠、Enterprise、API、セキュリティ、管理者機能、AIエージェント、検索・Grounding、Google Workspace、Microsoft 365、Android/iOS、監査証跡、AIガバナンス。

監査視点:
AIガバナンス、変更管理、アクセス管理、ログ管理、情報セキュリティ、AI利用ルール、出力品質管理、監査証跡、業務導入リスク。

レポート構成:
1. 今週の重要アップデートTOP5
2. ChatGPT / OpenAI
3. Gemini / Google
4. Claude / Anthropic
5. Microsoft Copilot
6. 内部監査への示唆
7. 今後ウォッチすべき事項
8. 情報源

TOP5は「ニュースとして目立つもの」ではなく、企業の管理・監査への影響が大きいものを優先。
各項目に「新規/変更/継続/終了」の区分と、★★★/★★☆/★☆☆の重要度を付ける。
各項目は「確認できた事実」と「監査上の確認事項」を分ける。

HTML要件:
- 完全なHTML文書
- 外部CSS/JavaScriptなし、CSSは内部記述
- スマートフォン対応
- 読みやすく、前回より極端に短くしない
- TOP5だけでなく各社セクションにも具体的な事実を1～3件程度記載
- 各重要事項には可能なら情報源リンクを付ける
- 情報源一覧には実際に使用したURLだけを掲載
- 「今後ウォッチすべき事項」を必ず含める
- 最後に「このレポートは公開情報に基づく情報整理であり、監査判断そのものを代替するものではありません。」を入れる
- HTML以外の説明文は禁止

直近7日間のニュース候補:
{news_context}

前回レポート:
{previous_html}

現在のHTML:
{current_html}
"""

url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
payload = {"contents": [{"parts": [{"text": prompt}]}]}
request = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"},
    method="POST",
)

print("Calling Gemini API...", flush=True)
max_attempts = 5
retryable_statuses = {429, 500, 502, 503, 504, 520}
result = None
for attempt in range(1, max_attempts + 1):
    try:
        print(f"Gemini API attempt {attempt}/{max_attempts}...", flush=True)
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
        print(f"Gemini API request succeeded on attempt {attempt}/{max_attempts}.", flush=True)
        break
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body).get("error", {})
            reason = err.get("status") or err.get("message") or body[:500]
        except (TypeError, ValueError):
            reason = body[:500]
        print(f"Gemini API HTTP {e.code}: {reason}", flush=True)
        if e.code not in retryable_statuses or attempt == max_attempts:
            raise RuntimeError(f"Gemini API request failed: HTTP {e.code}: {reason}")
        retry_after = None
        header = e.headers.get("Retry-After") if e.headers else None
        if header:
            try:
                retry_after = min(max(int(header), 1), 300)
            except ValueError:
                pass
        wait_seconds = retry_after if retry_after is not None else min(60 * (2 ** (attempt - 1)), 300)
        print(f"Transient Gemini error. Retrying in {wait_seconds} seconds...", flush=True)
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
