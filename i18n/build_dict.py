# -*- coding: utf-8 -*-
# 从当前 csharp/KurumiSim/renderer/index.html 重新抽取中文字面量，合并既有 strings.json 翻译，
# 用本地 Ollama (hy-mt2) 补齐缺失项，产出 i18n-data.js（C# 单文件 EXE 内嵌的字典）。
import json, re, time, urllib.request, sys

ROOT = ".."
HTML = f"{ROOT}/csharp/KurumiSim/renderer/index.html"
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
        if r.lstrip().startswith("//") or r.lstrip().startswith("/*"):   # JS 注释不是文案
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
try:   # 复用当前已发布的字典，只翻真正新增的串
    _js = open(f"{ROOT}/csharp/KurumiSim/renderer/i18n-data.js", encoding="utf-8").read()
    LIVE = json.loads(_js[_js.index("=") + 1:].rstrip().rstrip(";"))
except Exception:
    LIVE = {}
merged = {}   # zh -> {en,ja,ko,count}
for z in phrases:
    e = old_map.get(z, {})
    lv = LIVE.get(z, {})
    merged[z] = {
        "en": lv.get("en") or e.get("en", "") or "",
        "ja": lv.get("ja") or e.get("ja", "") or "",
        "ko": lv.get("ko") or e.get("ko", "") or "",
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
    last = None
    for attempt in range(3):                       # Ollama 偶尔 RemoteDisconnected，重试即可
        try:
            req = urllib.request.Request(API, data=b, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return clean(json.load(resp).get("response", ""))
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    print(f"  [warn] 翻译失败({lang}): {text[:24]} -> {last}")
    return ""

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
open(f"{ROOT}/csharp/KurumiSim/renderer/i18n-data.js", "w", encoding="utf-8").write(js)

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
    # 网络/代理类（机翻会把「代理」翻成 agent，需锁定为 proxy）
    "代理已更新": {"en": "Proxy updated", "ja": "プロキシを更新しました", "ko": "프록시가 업데이트되었습니다"},
    "代理设置失败": {"en": "Proxy setup failed", "ja": "プロキシ設定に失敗しました", "ko": "프록시 설정 실패"},
    "直连":   {"en": "Direct", "ja": "直接接続", "ko": "직접 연결"},
    # 画布十字光标的 OHLC 单字标签（单字键只在整段相等时替换，不会误伤正文）
    "开":     {"en": "O", "ja": "始値", "ko": "시가"},
    "高":     {"en": "H", "ja": "高値", "ko": "고가"},
    "低":     {"en": "L", "ja": "安値", "ko": "저가"},
    "收":     {"en": "C", "ja": "終値", "ko": "종가"},
    # 爆仓弹窗
    "空中飞人！": {"en": "Game over!", "ja": "人生終了！", "ko": "인생 종료!"},
    # A股相关
    "A股":    {"en": "A-shares", "ja": "A株", "ko": "A주"},
    "下单面板": {"en": "Order panel", "ja": "注文パネル", "ko": "주문 패널"},
    "均线":   {"en": "MA", "ja": "移動平均", "ko": "이동평균"},
    # AI 策略选股
    "AI 策略选股": {"en": "AI Strategy Picks", "ja": "AI戦略銘柄選定", "ko": "AI 전략 종목"},
    "趋势动量": {"en": "Trend Momentum", "ja": "トレンドモメンタム", "ko": "추세 모멘텀"},
    "均线金叉": {"en": "MA Golden Cross", "ja": "移動平均ゴールデンクロス", "ko": "이평선 골든크로스"},
    "超跌反弹": {"en": "Oversold Bounce", "ja": "売られすぎ反発", "ko": "과매도 반등"},
    "区间突破": {"en": "Range Breakout", "ja": "レンジブレイク", "ko": "레인지 돌파"},
    "低波动稳健": {"en": "Low Volatility", "ja": "低ボラ安定", "ko": "저변동 안정"},
    "开始筛选": {"en": "Start Scan", "ja": "スクリーニング開始", "ko": "선별 시작"},
    "市场范围": {"en": "Market", "ja": "対象市場", "ko": "시장 범위"},
    "取前几名": {"en": "Top N", "ja": "上位N件", "ko": "상위 N개"},
    "全部市场": {"en": "All markets", "ja": "全市場", "ko": "전체 시장"},
    "查看":   {"en": "View", "ja": "表示", "ko": "보기"},
    "标记":   {"en": "Tag", "ja": "タグ付け", "ko": "표시"},
    "取消标记": {"en": "Untag", "ja": "解除", "ko": "해제"},
    "清除全部 AI 标记": {"en": "Clear all AI tags", "ja": "AIタグを全解除", "ko": "AI 표시 전체 해제"},
    "A股全市场（实时）": {"en": "CN market (live)", "ja": "A株全市場（リアルタイム）", "ko": "A주 전체 시장(실시간)"},
    "内置品种 · 全部": {"en": "Built-in · all", "ja": "内蔵銘柄・全て", "ko": "내장 종목 · 전체"},
    "加自选": {"en": "Add", "ja": "追加", "ko": "추가"},
    "收起":   {"en": "Collapse", "ja": "たたむ", "ko": "접기"},
    "展开":   {"en": "Expand", "ja": "ひらく", "ko": "펼치기"},
    "上海":   {"en": "Shanghai", "ja": "上海", "ko": "상하이"},
    "佣金 0.025%（低消 5）": {"en": "Commission 0.025% (min 5)", "ja": "手数料 0.025%（最低5元）", "ko": "수수료 0.025%(최소 5)"},
    "过户费 0.001%": {"en": "Transfer fee 0.001%", "ja": "名義変更料 0.001%", "ko": "명의변경 수수료 0.001%"},
    "印花税 0.05%（卖出）": {"en": "Stamp duty 0.05% (on sell)", "ja": "印紙税 0.05%（売却時）", "ko": "인지세 0.05%(매도 시)"},
    "爆仓":   {"en": "Blown up", "ja": "強制決済", "ko": "강제 청산"},
    "认输":   {"en": "I give up", "ja": "降参", "ko": "항복"},
    "总权益": {"en": "Equity", "ja": "総資産", "ko": "총자산"},
    "本金":   {"en": "Principal", "ja": "元本", "ko": "원금"},
    "账户已资不抵债": {
        "en": "Equity has gone negative.",
        "ja": "資産がマイナスになりました。",
        "ko": "자산이 마이너스가 되었습니다."},
    "重置账户可重开一局": {
        "en": "Reset the account to start over.",
        "ja": "リセットすれば最初からやり直せます。",
        "ko": "초기화하면 처음부터 다시 시작할 수 있습니다."},
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
open(f"{ROOT}/csharp/KurumiSim/renderer/i18n-data.js", "w", encoding="utf-8").write(js)
print(f"纠正后字典条目: {len(dict_items)}")
