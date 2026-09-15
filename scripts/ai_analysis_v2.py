import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set.")

JST = timezone(timedelta(hours=9))
report_date = datetime.now(JST).strftime("%Y年%-m月%-d日")
MODEL = "gemini-3.1-flash-lite"


class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self.in_title:
            self.title += (" " if self.title else "") + text
        if not self.skip_depth:
            self.parts.append(text)

    def text(self):
        return " ".join(self.parts)


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def fetch_url(url, timeout=20, max_chars=4500):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AI-Update-Report/2.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(800000)
    if "html" not in content_type.lower() and not raw.lstrip().startswith(b"<"):
        return final_url, ""
    parser = TextExtractor()
    parser.feed(raw.decode("utf-8", errors="ignore"))
    text = re.sub(r"\s+", " ", parser.text()).strip()
    return final_url, text[:max_chars]


def fetch_news(query, limit=4):
    params = urllib.parse.urlencode({
        "q": f"{query} when:7d",
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    })
    rss_url = f"https://news.google.com/rss/search?{params}"
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            root = ET.fromstring(response.read())
        results = []
        seen = set()
        for item in root.findall("./channel/item"):
            if len(results) >= limit:
                break
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            source = item.find("source")
            source_name = (source.text or "").strip() if source is not None else ""
            if not title or not link or link in seen:
                continue
            seen.add(link)
            try:
                final_url, article_text = fetch_url(link)
            except Exception as e:
                print(f"Article fetch failed: {title}: {e}", flush=True)
                final_url, article_text = link, ""
            results.append({
                "title": title,
                "source": source_name,
                "date": pub_date,
                "rss_url": link,
                "article_url": final_url,
                "article_text": article_text,
            })
        return results
    except Exception as e:
        print(f"News context fetch failed for {query}: {e}", flush=True)
        return []


def format_news(items):
    if not items:
        return "(No usable recent items found.)"
    blocks = []
    for i, item in enumerate(items, 1):
        blocks.append(
            f"[{i}] title={item['title']}\n"
            f"source={item['source']}\n"
            f"date={item['date']}\n"
            f"article_url={item['article_url']}\n"
            f"article_text={item['article_text'] or '(article text unavailable; treat as candidate only)'}"
        )
    return "\n\n".join(blocks)


current_html = read_file("index.html")
try:
    previous_html = subprocess.check_output(
        ["git", "show", "HEAD~1:index.html"], stderr=subprocess.DEVNULL
    ).decode("utf-8", errors="ignore")
except Exception:
    previous_html = ""

news_groups = {
    "OpenAI / official": fetch_news("site:openai.com ChatGPT OpenAI", 4),
    "Google / official": fetch_news("site:blog.google Gemini Google AI", 4),
    "Anthropic / official": fetch_news("site:anthropic.com Claude Anthropic", 4),
    "Microsoft / official": fetch_news("site:techcommunity.microsoft.com Copilot Microsoft", 4),
    "Broader corroboration": fetch_news("OpenAI ChatGPT OR Google Gemini OR Anthropic Claude OR Microsoft Copilot", 4),
}

news_context = "\n\n".join(
    f"### {name}\n{format_news(items)}" for name, items in news_groups.items()
)

prompt = f"""
あなたは企業の内部監査・IT統制・AIガバナンス担当者向けの週刊レポート編集者です。

基準日: {report_date}
対象: ChatGPT/OpenAI、Gemini/Google、Claude/Anthropic、Microsoft Copilot

【最重要：証拠優先】
- 以下のニュース候補と記事本文だけを根拠材料にする。
- 重要な事実は一次情報、特に各社公式記事を最優先する。
- article_url は実際に取得・確認したURLであり、情報源リンクとして使用してよい。
- 記事本文が取得できなかった候補は「候補」として扱い、本文から事実を推測しない。
- モデル名、製品名、料金、提供地域、提供時期、機能、仕様を想像で補完しない。
- 情報源URLを創作しない。下記にある article_url のみを使用する。
- 事実と監査上の分析を明確に分ける。
- 企業公式情報と報道が食い違う場合は、食い違いを明記する。
- 「確認できた事実」「監査上の確認事項」「考察」を混同しない。
- 前回レポートとの差分を重視し、変化がない項目は無理にニュース化しない。

【ニュース選定】
TOP5はニュースとして目立つ順ではなく、企業の管理・内部監査・IT統制への影響が大きい順に選ぶ。
各項目に「新規/変更/継続/終了」と重要度「★★★/★★☆/★☆☆」を付ける。
各社セクションには、確認できた重要事項を1～3件程度記載する。

【内部監査視点】
AIガバナンス、変更管理、アクセス管理、ログ管理、情報セキュリティ、AI利用ルール、出力品質管理、監査証跡、業務導入リスクを重視する。

【内部監査プロセスの高度化への有用性】
今週確認された具体的なAI製品の機能・変更を起点に、内部監査そのものをどう高度化できるかを考察する。
一般論だけにせず、次の7工程に結び付ける。
①リスク評価 → ②監査計画 → ③資料収集 → ④分析・検証 → ⑤指摘・原因分析 → ⑥報告 → ⑦フォローアップ

特に以下を検討する。
- リスクアセスメント：規程・業務情報・過去監査結果からリスク候補を抽出し、監査対象選定を高度化できるか。
- 監査計画：リスクベース監査の優先順位、監査範囲、サンプル設計、重点領域設定に使えるか。
- 監査手続：証憑・ログ・規程・契約・議事録等の大量資料の検索、比較、要約、異常候補抽出に使えるか。
- コントロール評価：規程と実運用の差異、職務分掌、アクセス権、承認、変更管理などの確認を支援できるか。
- 不正・異常検知：人手では見つけにくいパターンを補助的に発見できるか。誤検知・見逃しも明記する。
- 根拠・監査証跡：AI回答をそのまま監査証拠にせず、原文・ログ・参照データ・判断者を追跡できる仕組みが必要か。
- 監査報告：指摘事項、原因分析、改善提案、経営向け要約をどう効率化できるか。
- 継続的監査：AIと自動化により、定期監査から継続的モニタリングへ発展できるか。
- 監査品質：品質が上がる領域と、専門家レビューがより重要になる領域を分ける。
- AI自身の監査可能性：利用ログ、プロンプト、参照データ、モデル変更、権限、出力レビューをどう管理するか。

重要なのは「AIに監査判断を任せる」のではなく、「監査人の判断を支える情報処理能力を拡張する」こと。
今週のアップデートと直接結び付かない工程は、無理に関連付けない。
500～900字程度で、具体例・効果・限界・人間によるレビューの必要性を含める。

【レポート構成】
1. 今週の重要アップデートTOP5
2. ChatGPT / OpenAI
3. Gemini / Google
4. Claude / Anthropic
5. Microsoft Copilot
6. 内部監査への示唆
7. 内部監査プロセスの高度化への有用性
8. 今後ウォッチすべき事項
9. 情報源

【HTML要件】
- 完全なHTML文書
- 外部CSS/JavaScriptなし、CSSは内部記述
- スマートフォン対応
- 前回より極端に短くしない
- 「内部監査プロセスの高度化への有用性」を独立セクションにする
- 7工程の対応関係を表または簡潔なフロー図で視覚化する
- 各重要事項には可能な限り「記事そのもの」へのリンクを付ける
- 情報源一覧には実際に使用した article_url だけを掲載する
- 「今後ウォッチすべき事項」を必ず含める
- 最後に「このレポートは公開情報に基づく情報整理であり、監査判断そのものを代替するものではありません。」を入れる
- HTML以外の説明文は禁止

【直近7日間のニュース候補・取得記事】
{news_context}

【前回レポート】
{previous_html}

【現在のHTML】
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
        with urllib.request.urlopen(request, timeout=180) as response:
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
