import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set.")

MODEL = "gemini-3.1-flash-lite"


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def previous_html():
    try:
        return subprocess.check_output(
            ["git", "show", "HEAD~1:index.html"], stderr=subprocess.DEVNULL
        ).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def extract_audit_section(html):
    if not html:
        return ""
    patterns = [
        r"(<section[^>]*>.*?内部監査プロセスの高度化への有用性.*?</section>)",
        r"(<article[^>]*>.*?内部監査プロセスの高度化への有用性.*?</article>)",
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.I | re.S)
        if m:
            return m.group(1)
    return ""


def has_main_report(html):
    required = [
        "今週の重要アップデートTOP5",
        "ChatGPT / OpenAI",
        "Gemini / Google",
        "Claude / Anthropic",
        "Microsoft Copilot",
        "内部監査への示唆",
        "今後ウォッチすべき事項",
        "情報源",
    ]
    return bool(html) and all(text in html for text in required)


def call_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    retryable = {429, 500, 502, 503, 504, 520}
    for attempt in range(1, 6):
        try:
            print(f"Audit section Gemini attempt {attempt}/5...", flush=True)
            with urllib.request.urlopen(request, timeout=180) as response:
                data = json.loads(response.read().decode("utf-8"))
            return "".join(
                p.get("text", "")
                for p in data["candidates"][0]["content"]["parts"]
                if isinstance(p, dict)
            ).strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code not in retryable or attempt == 5:
                raise RuntimeError(f"Gemini audit-section request failed: HTTP {e.code}: {body[:500]}")
            retry_after = None
            if e.headers:
                value = e.headers.get("Retry-After")
                if value:
                    try:
                        retry_after = min(max(int(value), 1), 300)
                    except ValueError:
                        pass
            wait = retry_after if retry_after is not None else min(60 * (2 ** (attempt - 1)), 300)
            print(f"Transient error; retrying in {wait} seconds...", flush=True)
            time.sleep(wait)

    raise RuntimeError("Gemini audit-section request returned no result.")


current = read("index.html")
previous = previous_html()

# Gemini can occasionally return only the tail of a long HTML document.
# Never let that truncate the established weekly report. If the current output
# is missing the main report sections, keep the previous complete report as the
# base and update only the fixed audit-process section below.
if has_main_report(current):
    base_html = current
    print("Current AI report contains the main sections; using it as the base.", flush=True)
elif has_main_report(previous):
    base_html = previous
    print("Current AI report is incomplete; preserving the previous complete report.", flush=True)
else:
    raise RuntimeError("Neither current nor previous index.html contains the complete weekly report.")

previous_section = extract_audit_section(previous)

prompt = f"""
あなたは内部監査・IT統制・AIガバナンスの編集者です。
現在生成された週刊AIレポートの中にある「内部監査プロセスの高度化への有用性」セクションだけを再構成してください。

【絶対条件】
監査7工程を常設の7行として、必ず①～⑦すべて表示してください。更新がない工程も絶対に省略しません。
番号が飛ぶと、7工程を知らない読者には「工程の抜け漏れ」と誤解されるためです。

7工程は固定です。
① リスク評価
② 監査計画
③ 資料収集
④ 分析・検証
⑤ 指摘・原因分析
⑥ 報告
⑦ フォローアップ

【各行の判定】
- 今回のレポート内容と前回の同セクションを比較し、今回その工程に新しいAIアップデートによる具体的な変化・有用性がある場合は「更新あり」とする。
- それ以外は必ず「更新なし」とする。
- 「更新なし」でも、その工程について前回までに確認されている有用性・注意点などの過去情報を簡潔に残す。
- 「更新あり」は強調表示する。HTMLでは class="updated" を使うこと。
- 「更新なし」は class="unchanged" を使うこと。
- 更新の判定は、単なる言い換えや同じ情報の再掲ではなく、今回新たに確認された機能・変更・運用上の意味に基づく。
- AIに監査判断を任せるという表現は禁止。監査人の判断を支援する位置付けにする。
- 更新ありでも、根拠が今回のレポートにない場合は「更新なし」にする。

【表示形式】
HTMLの <section> として返してください。外部CSSは禁止です。
見出しは「内部監査プロセスの高度化への有用性」としてください。
7工程を表形式で、最低限次の列を持たせてください。
「工程」「今回の状況」「内容」

「今回の状況」は、更新ありなら <span class="status updated">更新あり</span>、更新なしなら <span class="status unchanged">更新なし</span> としてください。
更新ありの行には「今回の変更点→監査業務への意味」を具体的に記載してください。
更新なしの行には「現時点で確認されている過去情報」を記載してください。
最後に短い注意書きとして、AI出力は監査証拠そのものではなく、原資料・ログ・判断者による検証が必要であることを記載してください。

【今回のレポート】
{base_html}

【前回レポートの同セクション】
{previous_section or '(前回セクションなし)'}

HTML以外は返さないでください。
"""

section = call_gemini(prompt)
if section.startswith("```"):
    section = re.sub(r"^```(?:html)?\s*", "", section, flags=re.I)
    section = re.sub(r"\s*```$", "", section)
section = section.strip()

if "内部監査プロセスの高度化への有用性" not in section or section.count("リスク評価") < 1:
    raise RuntimeError("Generated audit section is missing required content.")

if section.count("更新なし") + section.count("更新あり") < 7:
    raise RuntimeError("Generated audit section does not contain all seven status entries.")

patterns = [
    r"<section[^>]*>.*?内部監査プロセスの高度化への有用性.*?</section>",
    r"<article[^>]*>.*?内部監査プロセスの高度化への有用性.*?</article>",
]
new_html = base_html
for pattern in patterns:
    if re.search(pattern, new_html, re.I | re.S):
        new_html = re.sub(pattern, section, new_html, count=1, flags=re.I | re.S)
        break
else:
    marker = re.search(r"<section[^>]*>.*?(今後ウォッチすべき事項|ウォッチすべき事項).*?</section>", new_html, re.I | re.S)
    if marker:
        new_html = new_html[:marker.start()] + section + "\n" + new_html[marker.start():]
    else:
        new_html = new_html.replace("</main>", section + "\n</main>", 1)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(new_html)

print("Persistent seven-stage audit process section updated successfully.", flush=True)
