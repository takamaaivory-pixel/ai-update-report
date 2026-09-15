import json
import os
import re
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


def fetch_news(query, limit=6):
    params = urllib.parse.urlencode({"q": f"{query} when:7d", "hl": "ja", "gl": "JP", "ceid": "JP:ja"})
    url = f"https://news.google.com/rss/search?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            root = ET.fromstring(response.read())
        rows = []
        for item in root.findall("./channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if title:
                rows.append(f"- {title} | date={pub} | link={link}")
        return "\n".join(rows) or "(no recent items)"
    except Exception as e:
        print(f"News fetch failed: {e}", flush=True)
        return "(news unavailable)"


def gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(1, 6):
        try:
            req = urllib.request.Request(url, data=body, headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"}, method="POST")
            print(f"Gemini API attempt {attempt}/5...", flush=True)
            with urllib.request.urlopen(req, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            print(f"Gemini API request succeeded on attempt {attempt}/5.", flush=True)
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            print(f"Gemini API HTTP {e.code}: {detail}", flush=True)
            if e.code not in {429, 500, 502, 503, 504, 520} or attempt == 5:
                raise RuntimeError(f"Gemini API request failed: HTTP {e.code}: {detail}")
            time.sleep(min(60 * (2 ** (attempt - 1)), 300))
    raise RuntimeError("Gemini API returned no result")


def section_pattern(title):
    return re.compile(r'(<section>\s*<h2>' + re.escape(title) + r'</h2>).*?(</section>)', re.S)


def replace_section(html, title, inner):
    pat = section_pattern(title)
    replacement = r'\1' + "\n" + inner.strip() + r"\n\2"
    new_html, n = pat.subn(replacement, html, count=1)
    if n != 1:
        raise RuntimeError(f"Could not locate section: {title}")
    return new_html


def li_html(values):
    if not isinstance(values, list):
        values = [values]
    return "\n".join(f"<li>{str(v)}</li>" for v in values if str(v).strip())


def main():
    with open("templates/baseline_index.html", encoding="utf-8") as f:
        html = f.read()

    news = "\n\n".join([
        "### OpenAI\n" + fetch_news("OpenAI ChatGPT"),
        "### Google Gemini\n" + fetch_news("Google Gemini AI"),
        "### Anthropic Claude\n" + fetch_news("Anthropic Claude AI"),
        "### Microsoft Copilot\n" + fetch_news("Microsoft Copilot AI"),
    ])

    prompt = f'''基準日 {report_date}。以下の直近7日ニュース候補を使い、企業の内部監査・AIガバナンス向け週報の「差し替え用データ」を作ってください。
HTML全体は禁止。JSONだけ返してください。キーは top5, openai, gemini, claude, microsoft, audit_implication, watch。
各ニュースは「区分（新規/変更/継続/終了）」「重要度」「事実」「監査上の確認事項」を含む短いHTML不要の文章にしてください。
audit_implicationでは、今週の具体的なAI機能から内部監査7工程（①リスク評価 ②監査計画 ③資料収集 ④分析・検証 ⑤指摘・原因分析 ⑥報告 ⑦フォローアップ）のどこが高度化するかを具体的に考察してください。AIを監査判断そのものにしないこと、証拠の原本確認、人間レビューも明記してください。
事実を捏造せず、確認できないものは採用しないでください。
ニュース候補:\n{news}'''

    raw = gemini(prompt).strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Gemini did not return JSON")
    data = json.loads(raw[start:end + 1])

    # Only replace the contents of known sections. The surrounding HTML and all other sections remain untouched.
    top5 = data.get("top5", [])
    top5_html = "<ol>" + li_html(top5) + "</ol>"
    html = replace_section(html, "1. 今週の重要アップデートTOP5", top5_html)
    for key, title in [("openai", "2. ChatGPT / OpenAI"), ("gemini", "3. Gemini / Google"), ("claude", "4. Claude / Anthropic"), ("microsoft", "5. Microsoft Copilot")]:
        html = replace_section(html, title, "<ul>" + li_html(data.get(key, [])) + "</ul>")
    html = replace_section(html, "6. 内部監査への示唆", "<p>" + str(data.get("audit_implication", "")) + "</p>")
    html = replace_section(html, "8. 今後ウォッチすべき事項", "<ul>" + li_html(data.get("watch", [])) + "</ul>")
    html = html.replace("基準日：</strong>2026年9月15日", f"基準日：</strong>{report_date}")

    # Safety validation: never publish a structurally incomplete report.
    required = [
        "1. 今週の重要アップデートTOP5", "2. ChatGPT / OpenAI", "3. Gemini / Google",
        "4. Claude / Anthropic", "5. Microsoft Copilot", "6. 内部監査への示唆",
        "7. 内部監査プロセスの高度化への有用性", "8. 今後ウォッチすべき事項", "9. 情報源",
        "① リスク評価", "② 監査計画", "③ 資料収集", "④ 分析・検証", "⑤ 指摘・原因分析", "⑥ 報告", "⑦ フォローアップ"
    ]
    missing = [x for x in required if x not in html]
    if missing:
        raise RuntimeError("Final report validation failed: " + ", ".join(missing))

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Report generated successfully for {report_date}; full structure preserved.", flush=True)


if __name__ == "__main__":
    main()
