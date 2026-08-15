#!/usr/bin/env python3
"""
build_paper.py — ประกอบชิ้นส่วน HTML เป็นบทความฉบับเดียว พร้อมตรวจความถูกต้องของโครง

ทำไมต้องมีสคริปต์นี้: ถ้าปล่อยให้ AI เขียนไฟล์ HTML ทั้งไฟล์เอง มันจะเสียเวลาไปกับ
การประดิษฐ์ CSS ใหม่ทุกครั้ง และบางครั้งเขียนร่างยาวเกินแล้วรื้อเขียนใหม่ทั้งฉบับ
สคริปต์นี้ถือ CSS กับโครงเปลือกไว้เอง ⇒ AI เขียนแค่ <section> แล้วประกอบให้เสร็จ

วิธีใช้:
    python build_paper.py --parts ./paper/_parts --out ./paper/TACC.html \\
        --title "TACC — ชื่อบทความ" --subtitle "คำโปรย" \\
        --tag "SET · TACC" --tag "10 ส.ค. 2026"

ชิ้นส่วนใน --parts คือไฟล์ .html ที่มีแต่ <section> ล้วน ๆ
เรียงตามชื่อไฟล์ ⇒ ตั้งชื่อขึ้นต้นด้วยเลขเพื่อคุมลำดับ เช่น 05-front.html, 10-a.html

สคริปต์จะตรวจให้ด้วยว่า แท็กเปิด/ปิดครบไหม และมีการเรียกไฟล์ภายนอกหลุดมาไหม
(บทความต้องเปิดได้แบบออฟไลน์ ไม่พึ่ง CDN)
"""
import argparse
import html
import re
import sys
from datetime import date
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CSS = """
:root{
  --bg:#0f1923; --bg2:#141f2b; --card:#18242f; --line:#243444;
  --tx:#dbe6f0; --tx2:#9fb0c2; --tx3:#748699;
  --blue:#3b82f6; --amber:#f59e0b; --red:#ef4444; --green:#22c55e; --purple:#a78bfa;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--tx);
  font-family:"Sarabun","Segoe UI","Noto Sans Thai",system-ui,-apple-system,sans-serif;
  font-size:17px;line-height:1.85}
.wrap{max-width:920px;margin:0 auto;padding:24px 18px 80px}
h1{font-size:1.9rem;line-height:1.35;margin:.2em 0 .3em;letter-spacing:-.01em}
h2{font-size:1.35rem;margin:2.4em 0 .6em;padding-bottom:.35em;border-bottom:2px solid var(--line);color:#fff}
h3{font-size:1.1rem;margin:1.8em 0 .5em;color:#e8f1fa}
h4{font-size:1rem;margin:1.3em 0 .4em;color:var(--tx2);font-weight:700}
p{margin:.85em 0}
a{color:var(--blue);text-decoration:none}
a:hover{text-decoration:underline}
small{color:var(--tx3)}
code{background:#0b1219;padding:.1em .4em;border-radius:4px;font-size:.9em;color:#ffd79a}
hr{border:0;border-top:1px solid var(--line);margin:2.5em 0}
ul,ol{padding-left:1.3em}
li{margin:.4em 0}
.sub{color:var(--tx3);font-size:.92rem;margin-top:-.4em}
.tag{display:inline-block;font-size:.75rem;padding:.15em .6em;border-radius:999px;
  border:1px solid var(--line);color:var(--tx2);margin-right:.35em;background:#0d151d}
.tag.red{color:#ffb4b4;border-color:#5b2222;background:#1e1113}
.tag.amber{color:#ffd79a;border-color:#5c4318;background:#1e1810}
.tag.green{color:#a7f3c0;border-color:#1e5237;background:#101d16}
.tag.blue{color:#bfd9ff;border-color:#1f3c66;background:#0e1723}
.verdict{background:linear-gradient(160deg,#1a2a3a,#131e29);border:1px solid #2b4460;
  border-left:5px solid var(--amber);border-radius:12px;padding:18px 20px;margin:22px 0}
.verdict .big{font-size:1.18rem;font-weight:700;color:#ffdca8;line-height:1.65}
.verdict .num{font-size:.95rem;color:var(--tx2);margin-top:.6em}
.decode{background:#101c26;border:1px dashed #33506e;border-radius:12px;padding:16px 20px;margin:18px 0}
.decode h4{margin-top:0;color:#8fc0ff}
.decode ol{margin:.4em 0;padding-left:1.2em}
.decode li{margin:.45em 0;font-size:.97rem}
.box{border-radius:10px;padding:14px 18px;margin:1.4em 0;border-left:4px solid var(--line);background:var(--card)}
.box.warn{border-left-color:var(--red);background:#1b1214}
.box.key{border-left-color:var(--amber);background:#1c1710}
.box.quote{border-left-color:var(--blue);background:#101a26}
.box.quote .who{display:block;margin-top:.5em;color:var(--tx3);font-size:.88rem}
.box.good{border-left-color:var(--green);background:#101a14}
.box.note{border-left-color:var(--purple);background:#161329}
.box h4{margin-top:0}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:1.3em 0;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:520px;font-size:.92rem}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#101b25;color:#a9c4dd;font-weight:700;white-space:nowrap}
tbody tr:last-child td{border-bottom:0}
tbody tr:nth-child(even){background:#141e28}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pos{color:#7ee2a8}.neg{color:#ff9a9a}.mut{color:var(--tx3)}
.toc{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin:26px 0}
.toc h4{margin:0 0 .5em;color:#8fc0ff}
.toc ol{margin:0;padding-left:1.4em;columns:2;column-gap:26px}
.toc li{margin:.3em 0;font-size:.94rem;break-inside:avoid}
@media(max-width:640px){.toc ol{columns:1}}
.ladder{margin:1.2em 0}
.rung{border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:.7em 0;background:var(--card)}
.rung .head{font-weight:700;color:#fff;margin-bottom:.25em}
.rung .meta{font-size:.85rem;color:var(--tx3)}
.foot{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);color:var(--tx3);font-size:.86rem}
@media(max-width:640px){
  body{font-size:16px}
  h1{font-size:1.5rem}
  h2{font-size:1.18rem}
  .wrap{padding:18px 14px 60px}
}
"""

DISCLAIMER = (
    "เอกสารนี้เรียบเรียงจากเอกสารที่บริษัทและหน่วยงานกำกับเผยแพร่เอง "
    "จัดทำเพื่อการศึกษา <b>ไม่ใช่คำแนะนำการลงทุน</b> "
    "ผู้อ่านควรตรวจสอบตัวเลขกับเอกสารต้นฉบับก่อนใช้ตัดสินใจ"
)

STRIP = [
    (re.compile(r"(?is)^.*?<body[^>]*>"), ""),
    (re.compile(r"(?is)</body>.*$"), ""),
    (re.compile(r"(?is)<!doctype[^>]*>"), ""),
    (re.compile(r"(?is)</?html[^>]*>"), ""),
    (re.compile(r"(?is)<head\b.*?</head>"), ""),
    (re.compile(r"(?is)<style\b.*?</style>"), ""),
    (re.compile(r"(?is)<script\b.*?</script>"), ""),
]


def clean_fragment(text: str) -> str:
    """ตัดแท็กระดับเอกสารออก เผื่อ AI เผลอใส่มา — เก็บเฉพาะเนื้อใน"""
    if "<body" in text.lower():
        text = STRIP[0][0].sub("", text)
    for pat, rep in STRIP[1:]:
        text = pat.sub(rep, text)
    return text.strip()


def check(doc: str):
    """คืนรายการปัญหาของโครงเอกสาร — ว่างแปลว่าผ่าน"""
    problems = []
    for tag in ("section", "table", "div", "ol", "ul", "tbody", "thead"):
        o, c = len(re.findall(rf"<{tag}\b", doc)), len(re.findall(rf"</{tag}>", doc))
        if o != c:
            problems.append(f"แท็ก <{tag}> ไม่สมดุล: เปิด {o} ปิด {c}")
    ext = re.findall(r'(?:src|href)\s*=\s*"https?://[^"]+"', doc)
    ext = [e for e in ext if not re.search(r'href\s*=\s*"https?://[^"]*"', e) or "src" in e]
    if ext:
        problems.append(f"อ้างไฟล์ภายนอก {len(ext)} แห่ง — บทความต้องเปิดออฟไลน์ได้")
    if re.search(r"\sstyle\s*=", doc):
        problems.append("มี style= ฝังในแท็ก — ให้ใช้คลาสที่มีอยู่แทน")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="ประกอบชิ้นส่วน HTML เป็นบทความฉบับเดียว")
    ap.add_argument("--parts", required=True, help="โฟลเดอร์ที่เก็บชิ้นส่วน .html")
    ap.add_argument("--out", required=True, help="ไฟล์บทความปลายทาง")
    ap.add_argument("--title", required=True, help="หัวเรื่อง")
    ap.add_argument("--subtitle", default="", help="คำโปรยใต้หัวเรื่อง")
    ap.add_argument("--tag", action="append", default=[], help="ป้ายบนหัว ใส่ซ้ำได้")
    ap.add_argument("--sources", default="", help="ย่อหน้าแหล่งข้อมูลท้ายเล่ม")
    args = ap.parse_args()

    pdir = Path(args.parts)
    if not pdir.is_dir():
        print(f"ไม่พบโฟลเดอร์ชิ้นส่วน: {pdir}", file=sys.stderr)
        return 1
    frags = sorted(pdir.glob("*.html"))
    if not frags:
        print(f"ไม่มีไฟล์ .html ใน {pdir}", file=sys.stderr)
        return 1

    tags = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in args.tag)
    head = [
        "<!doctype html>", '<html lang="th">', "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(args.title)}</title>",
        f"<style>{CSS}</style>", "</head>", "<body>", '<div class="wrap">', "",
        tags, "",
        f"<h1>{args.title}</h1>",
    ]
    if args.subtitle:
        head.append(f'<p class="sub">{args.subtitle}</p>')

    body = [clean_fragment(f.read_text(encoding="utf-8")) for f in frags]

    foot = ['<div class="foot">']
    if args.sources:
        foot.append(f"<p><b>แหล่งข้อมูล</b> — {args.sources}</p>")
    foot += [f"<p>จัดทำ {date.today().isoformat()} · {DISCLAIMER}</p>",
             "</div>", "", "</div>", "</body>", "</html>"]

    doc = "\n".join(head) + "\n\n" + "\n\n".join(body) + "\n\n" + "\n".join(foot) + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")

    visible = len(re.sub(r"<[^>]+>", "", doc))
    print(f"ประกอบแล้ว -> {out}")
    print(f"  ชิ้นส่วน {len(frags)} ไฟล์: {', '.join(f.name for f in frags)}")
    print(f"  ไฟล์ดิบ {len(doc):,} ตัวอักษร · มองเห็น {visible:,} ตัวอักษร · "
          f"{len(re.findall(r'<section', doc))} ส่วน · {len(re.findall(r'<table', doc))} ตาราง")

    problems = check(doc)
    if problems:
        print("  ⚠️ พบปัญหาโครงเอกสาร:")
        for p in problems:
            print(f"     - {p}")
        return 2
    print("  ✅ โครงเอกสารผ่าน — แท็กสมดุล ไม่มีการเรียกไฟล์ภายนอก")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
