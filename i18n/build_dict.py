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
    for attempt in range(2):                       # Ollama 偶尔 RemoteDisconnected，重试即可
        try:
            req = urllib.request.Request(API, data=b, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                return clean(json.load(resp).get("response", ""))
        except Exception as e:
            last = e
            if '404' in str(e): break           # 模型不存在：重试没意义，立刻跳过
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
    # AI 动态提示片段（模板串渲染后由 DOM 扫描替换）
    "拉取 A 股全市场实时快照…": {"en": "Fetching CN market snapshot…", "ja": "A株全市場スナップショット取得中…", "ko": "A주 전체 시장 스냅샷 가져오는 중…"},
    "拉取美股榜单（最活跃 / 涨幅 / 跌幅）…": {"en": "Fetching US market lists (actives / gainers / losers)…", "ja": "米国市場ランキング取得中…", "ko": "미국 시장 랭킹 가져오는 중…"},
    "只，按成交额取前": {"en": " matched, top by turnover ", "ja": " 件、出来高上位 ", "ko": " 개, 거래대금 상위 "},
    "进入策略打分…": {"en": " enter scoring…", "ja": " を採点…", "ko": " 채점 시작…"},
    "评分中": {"en": "Scoring ", "ja": "採点中 ", "ko": "채점 중 "},
    "（策略：": {"en": " (strategy: ", "ja": "（戦略：", "ko": " (전략: "},
    "个标的完成打分，取前": {"en": " instruments scored, top ", "ja": " 銘柄を採点、上位 ", "ko": " 종목 채점, 상위 "},
    "该范围内没有可评分的品种": {"en": "No instruments to score in this range", "ja": "この範囲に採点対象がありません", "ko": "이 범위에 채점할 종목이 없습니다"},
    "数据探针（测接口抓不抓得到）": {"en": "Data probe (test if sources respond)", "ja": "データプローブ（取得可否を確認）", "ko": "데이터 프로브 (수신 확인)"},
    "一键加入前": {"en": "Add top ", "ja": "上位 ", "ko": "상위 "},
    "个自选": {"en": " to watchlist", "ja": " 件をウォッチリストへ", "ko": " 개 관심종목 추가"},
    "美股候选": {"en": "US candidates ", "ja": "米国候補 ", "ko": "미국 후보 "},
    "① 全市场快照（新浪）：": {"en": "① Market snapshot (Sina): ", "ja": "① 全市場スナップショット（Sina）: ", "ko": "① 시장 스냅샷(新浪): "},
    "② 日线（腾讯": {"en": "② Daily bars (Tencent ", "ja": "② 日足（Tencent ", "ko": "② 일봉(텐센트 "},
    "③ 实时报价（腾讯）：": {"en": "③ Live quote (Tencent): ", "ja": "③ リアルタイム（Tencent）: ", "ko": "③ 실시간 시세(텐센트): "},
    "探针运行中…": {"en": "Probing…", "ja": "プローブ中…", "ko": "프로브 중…"},
    "抓到":   {"en": "Got", "ja": "取得", "ko": "수신"},
    "最后":   {"en": "Last", "ja": "最終", "ko": "마지막"},
    "失败":   {"en": "Failed", "ja": "失敗", "ko": "실패"},
    "样例":   {"en": "Sample", "ja": "サンプル", "ko": "샘플"},
    "全市场快照": {"en": "Market snapshot", "ja": "全市場スナップショット", "ko": "전체 시장 스냅샷"},
    # 公司名（Ollama 模型 404 期间手工补齐）
    "中国移动": {"en": "China Mobile", "ja": "チャイナモバイル", "ko": "차이나모바일"},
    "中国银行": {"en": "Bank of China", "ja": "中国銀行", "ko": "중국은행"},
    "建设银行": {"en": "China Construction Bank", "ja": "中国建設銀行", "ko": "중국건설은행"},
    "工商银行": {"en": "ICBC", "ja": "中国工商銀行", "ko": "중국공상은행"},
    "小米集团": {"en": "Xiaomi", "ja": "シャオミ", "ko": "샤오미"},
    "安踏体育": {"en": "ANTA Sports", "ja": "アンタ・スポーツ", "ko": "안타스포츠"},
    "快手":   {"en": "Kuaishou", "ja": "クアイショウ", "ko": "콰이셔우"},
    "银河娱乐": {"en": "Galaxy Entertainment", "ja": "ギャラクシー・エンターテインメント", "ko": "갤럭시 엔터테인먼트"},
    "任天堂": {"en": "Nintendo", "ja": "任天堂", "ko": "닌텐도"},
    "东京电子": {"en": "Tokyo Electron", "ja": "東京エレクトロン", "ko": "도쿄일렉트론"},
    "伊藤忠商事": {"en": "ITOCHU", "ja": "伊藤忠商事", "ko": "이토추상사"},
    "JR东日本": {"en": "JR East", "ja": "JR東日本", "ko": "JR동일본"},
    "摩根大通": {"en": "JPMorgan Chase", "ja": "JPモルガン", "ko": "JP모간"},
    "亚马逊": {"en": "Amazon", "ja": "アマゾン", "ko": "아마존"},
    "博通":   {"en": "Broadcom", "ja": "ブロードコム", "ko": "브로드컴"},
    "奈飞":   {"en": "Netflix", "ja": "Netflix", "ko": "Netflix"},
    "可口可乐": {"en": "Coca-Cola", "ja": "コカ・コーラ", "ko": "코카콜라"},
    "埃克森美孚": {"en": "ExxonMobil", "ja": "エクソンモービル", "ko": "엑손모빌"},
    "超威半导体": {"en": "AMD", "ja": "AMD", "ko": "AMD"},
    "甲骨文": {"en": "Oracle", "ja": "オラクル", "ko": "오라클"},
    "迪士尼": {"en": "Disney", "ja": "ディズニー", "ko": "디즈니"},
    "沃尔玛": {"en": "Walmart", "ja": "ウォルマート", "ko": "월마트"},
    "赛富时": {"en": "Salesforce", "ja": "セールスフォース", "ko": "세일즈포스"},
    "英特尔": {"en": "Intel", "ja": "インテル", "ko": "인텔"},
    "强生":   {"en": "Johnson & Johnson", "ja": "ジョンソン・エンド・ジョンソン", "ko": "존슨앤존슨"},
    "Visa":   {"en": "Visa", "ja": "Visa", "ko": "Visa"},
    "Meta":   {"en": "Meta", "ja": "Meta", "ko": "Meta"},
    "谷歌-A": {"en": "Alphabet A", "ja": "グーグルA", "ko": "구글 A"},
    "英伟达": {"en": "NVIDIA", "ja": "NVIDIA", "ko": "NVIDIA"},
    "微软":   {"en": "Microsoft", "ja": "Microsoft", "ko": "Microsoft"},
    "苹果":   {"en": "Apple", "ja": "Apple", "ko": "Apple"},
    "特斯拉": {"en": "Tesla", "ja": "Tesla", "ko": "Tesla"},
    "丰田汽车": {"en": "Toyota", "ja": "トヨタ自動車", "ko": "토요타"},
    "索尼":   {"en": "Sony", "ja": "ソニー", "ko": "소니"},
    "软银集团": {"en": "SoftBank Group", "ja": "ソフトバンクグループ", "ko": "소프트뱅크그룹"},
    "三菱UFJ": {"en": "MUFG", "ja": "三菱UFJ", "ko": "MUFG"},
    "基恩士": {"en": "Keyence", "ja": "キーエンス", "ko": "키엔스"},
    "日立制作所": {"en": "Hitachi", "ja": "日立製作所", "ko": "히타치"},
    "第一三共": {"en": "Daiichi Sankyo", "ja": "第一三共", "ko": "다이이찌산쿄"},
    "NTT":    {"en": "NTT", "ja": "NTT", "ko": "NTT"},
    "腾讯控股": {"en": "Tencent", "ja": "テンセント", "ko": "텐센트"},
    "汇丰控股": {"en": "HSBC", "ja": "HSBC", "ko": "HSBC"},
    "友邦保险": {"en": "AIA Group", "ja": "AIA", "ko": "AIA"},
    "香港交易所": {"en": "HKEX", "ja": "香港取引所", "ko": "홍콩거래소"},
    "中国平安": {"en": "Ping An", "ja": "中国平安", "ko": "핑안보험"},
    "贵州茅台": {"en": "Kweichow Moutai", "ja": "茅台酒", "ko": "구이저우마오타이"},
    "宁德时代": {"en": "CATL", "ja": "CATL", "ko": "CATL"},
    "比亚迪": {"en": "BYD", "ja": "BYD", "ko": "BYD"},
    "五粮液": {"en": "Wuliangye", "ja": "五糧液", "ko": "우량예"},
    "招商银行": {"en": "China Merchants Bank", "ja": "招商銀行", "ko": "초상은행"},
    "紫金矿业": {"en": "Zijin Mining", "ja": "紫金鉱業", "ko": "쯔진광업"},
    "东方财富": {"en": "East Money", "ja": "東方財富", "ko": "동방재부"},
    "台积电": {"en": "TSMC", "ja": "TSMC", "ko": "TSMC"},
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
