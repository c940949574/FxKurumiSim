# -*- coding: utf-8 -*-
"""用本地 Ollama (HY-MT1.5-1.8B) 批量翻译 i18n/strings.json。
用法: python translate.py --lang en [--limit N] [--force]
梗与专名留空，由人工补。
"""
import argparse, json, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "strings.json")
API = "http://127.0.0.1:11434/api/generate"
MODEL = "hy-mt2"

LANG_NAME = {"en": "English", "ja": "Japanese", "ko": "Korean"}

# 梗 / 专名 / 开局名，机翻一定出戏，留空人工补
MANUAL = {
    "一般韭菜", "韭菜", "神豪", "久留美", "Kurumi",
    "一般韭菜（20 万 CNY）", "久留美（1000 万 JPY）", "神豪（1 亿 USD）",
}


CJK = re.compile(r"[\u4e00-\u9fa5]")


def clean(out):
    """清掉模型输出的 /n、\n 字面量、前缀噪声与包裹字符"""
    out = out.replace("/n", " ").replace("/t", " ")
    out = re.sub(r"\s+", " ", out).strip(" :：-—")
    out = re.sub(r"^(?:s/|t/|n/|r/)+\s*", "", out)
    out = out.strip("/|\"'")
    return out


def translate(text, lang):
    prompt = (
        f"Translate the following text into {LANG_NAME[lang]}. "
        f"Note that you should only output the translated result without any additional explanation:\n\n{text}"
    )
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False, "keep_alive": "10m",
        "options": {"temperature": 0.1, "num_predict": 256},
    }).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r).get("response", "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=["en", "ja", "ko"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    data = json.load(open(JSON_PATH, encoding="utf-8"))
    # 金融术语：整条命中就直接取词表，不调模型（模型对术语不可靠）
    g = json.load(open(os.path.join(HERE, "glossary.json"), encoding="utf-8"))
    TERMS = g.get("terms", {})
    items = data["items"]
    # 先用术语表精确填充
    filled = 0
    for it in items:
        if it["zh"].strip() in TERMS and (args.force or not it.get(args.lang)):
            it[args.lang] = TERMS[it["zh"].strip()][args.lang]
            filled += 1
    if filled:
        json.dump(data, open(JSON_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"术语表直接填充 {filled} 条")
    todo = [it for it in items
            if (args.force or not it.get(args.lang)) and it["zh"] not in MANUAL
            and it["zh"].strip() not in TERMS]
    if args.limit:
        todo = todo[: args.limit]
    print(f"待翻 {len(todo)} 条 -> {args.lang}" + ("（从中文）" if args.lang == "en" else "（从英文枢轴）"))

    ok = fail = 0
    t0 = time.time()
    for i, it in enumerate(todo, 1):
        try:
            src = it["zh"] if args.lang == "en" else (it.get("en") or it["zh"])
            out = clean(translate(src, args.lang))
            # 目标语言里不该再出现中文；出现则判失败，留人工
            bad = (args.lang != "en") or bool(CJK.search(out))
            if out and len(out) < 400 and not (args.lang == "en" and CJK.search(out)) and out.lower() != src.lower():
                it[args.lang] = out
                ok += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f"  ! {it['id']} {e}")
        if i % 20 == 0:
            json.dump(data, open(JSON_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"  {i}/{len(todo)}  ok={ok} fail={fail}  {time.time()-t0:.0f}s")

    json.dump(data, open(JSON_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"完成: ok={ok} fail={fail} 用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
