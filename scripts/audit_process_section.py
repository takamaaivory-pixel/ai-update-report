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
            ["git", "show", "HEAD:index.html"], stderr=subprocess.DEVNULL
        ).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def extract_audit_section(html):
    if not html:
        return ""
    pattern = r"(<section[^>]*>\s*<h2>\s*7\.\s*内部監査プロセスの高度化への有用性\s*</h2>.*?</section>)"
    m = re.search(pattern, html, re.I | re.S)
    return m.group(1) if m else ""


def has_main_report(html):
    required = [
        "今週の重要アップデートTOP5",
        "ChatGPT / OpenAI",
        "Gemini / Google",
        "Claude / Anthropic",
        "Microsoft Copilot",
        "内部監査への示唆",
        "内部監査プロセスの高度化への有用性",
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
base_html = current
if not has_main_report(base_html):
    previous = previous_html()
    if has_main_report(previous):
        base_html = previous
        print("Current report is incomplete; preserving the previous complete report.", flush=True)
    else:
        raise RuntimeError("Current and previous index.html are both incomplete.")
else:
    print("Current report contains all nine main sections; preserving it as the base.", flush=True)

previous_section = extract_audit_section(previous_html())

prompt = f"""
あなたは内部監査・IT統制・AIガバナンスの編集者です。
現在の週刊AIレポートにある「内部監査プロセスの高度化への有用性」セクションだけを再構成してください。

絶対条件：監査7工程を必ず①～⑦すべて表示。更新なしも省略しない。
① リスク評価
② 監査計画
③ 資料収集
④ 分析・検証
⑤ 指摘・原因分析
⑥ 報告
⑦ フォローアップ

今回のレポートと前回セクションを比較し、新しいAIアップデートによる具体的な変化がある工程だけ「更新あり」、それ以外は「更新なし」。
更新なしでも過去情報を残す。更新ありは class="updated"、更新なしは class="unchanged" を使う。
更新ありの内容は「今回の変更点→監査業務への意味」を具体的に記載する。
AIに監査判断を任せる表現は禁止し、監査人の判断を支援する位置付けにする。

HTMLの <section> として返す。見出しは「7. 内部監査プロセスの高度化への有用性」。
表の列は「工程」「今回の状況」「内容」。最後にAI出力は監査証拠そのものではなく、原資料・ログ・判断者による検証が必要との注意書きを付ける。

【今回の完全レポート】
{base_html}

【前回の同セクション】
{previous_section or '(なし)'}

HTML以外は返さない。
"""

section = call_gemini(prompt)
section = re.sub(r"^```(?:html)?\s*", "", section, flags=re.I)
section = re.sub(r"\s*```$", "", section).strip()

if "内部監査プロセスの高度化への有用性" not in section:
    raise RuntimeError("Generated audit section is missing required heading.")
if section.count("更新なし") + section.count("更新あり") < 7:
    raise RuntimeError("Generated audit section does not contain all seven status entries.")

section_pattern = r"<section[^>]*>\s*<h2>\s*7\.\s*内部監査プロセスの高度化への有用性\s*</h2>.*?</section>"
if not re.search(section_pattern, base_html, re.I | re.S):
    raise RuntimeError("Existing report does not contain the fixed audit section to replace.")

new_html = re.sub(section_pattern, section, base_html, count=1, flags=re.I | re.S)

if not has_main_report(new_html):
    raise RuntimeError("Audit-section replacement damaged the main report structure.")

with open("index.html", "w", encoding="utf-8") as f:
    f.write(new_html)

print("Persistent seven-stage audit process section updated successfully without replacing other sections.", flush=True)
