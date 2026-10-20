# -*- coding: utf-8 -*-
# 从当前 app/renderer/index.html 重新抽取中文字面量，合并既有 strings.json 翻译，
# 用本地 Ollama (hy-mt2) 补齐缺失项，产出 i18n-data.js（app 实际加载的字典）。
import json, re, time, urllib.request, sys

ROOT = ".."
HTML = f"{ROOT}/app/renderer/index.html"
SRC = open(HTML, encoding="utf-8").read()
OLD = json.load(open("strings.json", encoding="utf-8"))["items"]
TAG = open(".tag.tmp").read().strip()

API = "http://127.0.0.1:11434/api/generate"

# ---------- 1. 抽取中文短语 ----------
def phrases_from(s):
    s = re.sub(r"\$\{[^}]*\}", " ", s)        # 丢弃 ${...} 插值
    s = re.sub(r"<[^>]+>", " ", s)            # 丢弃 html 标签
    runs = re.findall(r"[一-鿿A-Za-z0-9×·¥$%. ,，。、（）()/\-—:：%+#@]+", s)
    out = []
    for r in runs:
        r = r.strip(" ,，。、:：·\-—")   # 不strip括号/方括号，避免破坏键值
        if not re.search(r"[一-鿿]", r):
            continue
        if not (1 < len(r) <= 300):
            continue
        if re.search(r"(class=|function\s*=|return\s+|=>|://|addEventListener|\.map\(|\.filter\(|console\.)", r):
            continue
        out.append(r)
    return out

lits = re.findall(r"""["'`]([^"'`\n]*[一-鿿][^"'`\n]*)["'`]""", SRC)
nodes = re.findall(r">([^<>]+)<", SRC)
attrs = re.findall(r"""(?:placeholder|title|aria-label|alt|label)="([^"]*[一-鿿][^"]*)""", SRC)

cands = []
for s in lits + nodes + attrs:
    cands.extend(phrases_from(s))

from collections import Counter
cnt = Counter(cands)
phrases = [z for z, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))]
print(f"抽取中文短语 {len(phrases)} 条（去重，含计数）")

# ---------- 2. 合并既有翻译 ----------
old_map = {i["zh"]: i for i in OLD}
merged = {}   # zh -> {en,ja,ko,count}
for z in phrases:
    e = old_map.get(z, {})
    merged[z] = {
        "en": e.get("en", "") or "",
        "ja": e.get("ja", "") or "",
        "ko": e.get("ko", "") or "",
        "count": cnt[z],
    }

# ---------- 3. 翻译缺失项 ----------
def clean(o):
    o = o.replace("/n", " ").replace("/t", " ")
    o = re.sub(r"\s+", " ", o).strip(" :：-—/|'\"")
    o = re.sub(r"^(?:s/|t/|n/|r/|\\s|\\t|\\n)+\s*", "", o)
    return o.strip()

def tr(text, lang, model="hy-mt2"):
    p = (f"Translate the following text into {lang}. Note that you should only output the "
         f"translated result without any additional explanation:\n\n{text}")
    b = json.dumps({"model": model, "prompt": p, "stream": False, "keep_alive": "10m",
                    "options": {"temperature": 0.1, "num_predict": 400}}).encode()
    req = urllib.request.Request(API, data=b, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return clean(json.load(resp).get("response", ""))

def fix_brace(src, out):
    if "{}" in src and "{}" not in out:
        return out + "{}"
    return out

need = [z for z in phrases if not (merged[z]["en"] and merged[z]["ja"] and merged[z]["ko"])]
print(f"需要翻译（至少缺一语）: {len(need)}")
t0 = time.time()
for z in need:
    en = merged[z]["en"] or fix_brace(z, tr(z, "English"))
    merged[z]["en"] = en
    if not merged[z]["ja"]:
        merged[z]["ja"] = fix_brace(z, tr(en, "Japanese"))
    if not merged[z]["ko"]:
        merged[z]["ko"] = fix_brace(z, tr(en, "Korean"))
print(f"翻译完成 {time.time()-t0:.1f}s")

# ---------- 4. 产出 ----------
# 4a. i18n-data.js（app 加载）
dict_items = {z: {"en": merged[z]["en"], "ja": merged[z]["ja"], "ko": merged[z]["ko"]}
              for z in phrases if merged[z]["en"]}
js = "// 自动生成 by build_dict.py —— 四语言字典（zh 源 -> en/ja/ko）\n"
js += "// 源串为 key，值缺失时回退原文（中文）。\n"
js += "window.I18N_DICT = " + json.dumps(dict_items, ensure_ascii=False, indent=0) + ";\n"
open(f"{ROOT}/app/renderer/i18n-data.js", "w", encoding="utf-8").write(js)

# 4b. 合并副本（带日期标记，不覆盖 strings.json）
rec = [{"id": f"s{n:03d}", "zh": z, "en": merged[z]["en"], "ja": merged[z]["ja"],
        "ko": merged[z]["ko"], "count": merged[z]["count"]}
       for n, z in enumerate(phrases, 1)]
json.dump({"locale": "zh", "items": rec}, open(f"strings_{TAG}.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

empty = [z for z in phrases if not merged[z]["en"]]
print(f"写出 i18n-data.js（{len(dict_items)} 条） + strings_{TAG}.json")
print(f"仍缺英文: {len(empty)} -> {empty[:10]}")

# ---------- 5. 人工纠正覆盖层（核心交易术语 + 补齐缺失术语） ----------
CORRECTIONS = {
    # 交易动作术语（期货/期权标准说法 to-open / to-close）
    "品种":   {"en": "Instrument", "ja": "銘柄", "ko": "종목"},
    "限价":   {"en": "Limit", "ja": "指値", "ko": "지정가"},
    "市价":   {"en": "Market", "ja": "成行", "ko": "시장가"},
    "开仓":   {"en": "Open", "ja": "新規", "ko": "신규"},
    "平仓":   {"en": "Close", "ja": "決済", "ko": "청산"},
    "买入开仓": {"en": "Buy to Open", "ja": "新規買い", "ko": "신규 매수"},
    "卖出开仓": {"en": "Sell to Open", "ja": "新規売り", "ko": "신규 매도"},
    "买入平仓": {"en": "Buy to Close", "ja": "買い決済", "ko": "매수 청산"},
    "卖出平仓": {"en": "Sell to Close", "ja": "売り決済", "ko": "매도 청산"},
    "持仓":   {"en": "Position", "ja": "建玉", "ko": "포지션"},
    "挂单":   {"en": "Pending Order", "ja": "指値注文", "ko": "미체결 주문"},
    "结算":   {"en": "Settlement", "ja": "決済", "ko": "결제"},
    "加速":   {"en": "Accelerate", "ja": "加速", "ko": "가속"},
    "保证金率": {"en": "Margin Ratio", "ja": "証拠金率", "ko": "증거금률"},
    # 补齐：抽取阶段缺失的术语（作为子串也可命中）
    "历史记录": {"en": "History", "ja": "履歴", "ko": "기록"},
    "逐日盯市": {"en": "Mark-to-Market", "ja": "値洗い", "ko": "일일 정산"},
    "追加保证金": {"en": "Margin Call", "ja": "追証", "ko": "마진콜"},
    "模拟":   {"en": "Simulation", "ja": "シミュレーション", "ko": "시뮬레이션"},
    "风险":   {"en": "Risk", "ja": "リスク", "ko": "위험"},
    "交割":   {"en": "Delivery", "ja": "決済", "ko": "인도"},
}
for z, v in CORRECTIONS.items():
    if z not in merged:
        merged[z] = {"en": "", "ja": "", "ko": "", "count": 0}
    merged[z].update(v)
# 重新生成字典（含纠正项）
dict_items = {z: {"en": merged[z]["en"], "ja": merged[z]["ja"], "ko": merged[z]["ko"]}
              for z in merged if merged[z]["en"]}
js = "// 自动生成 by build_dict.py —— 四语言字典（zh 源 -> en/ja/ko）\n"
js += "// 源串为 key，值缺失时回退原文（中文）。\n"
js += "window.I18N_DICT = " + json.dumps(dict_items, ensure_ascii=False, indent=0) + ";\n"
open(f"{ROOT}/app/renderer/i18n-data.js", "w", encoding="utf-8").write(js)
print(f"纠正后字典条目: {len(dict_items)}")
