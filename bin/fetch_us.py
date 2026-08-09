#!/usr/bin/env python3
"""
fetch_us.py — ดึงเอกสารต้นฉบับของหุ้นสหรัฐจาก SEC EDGAR

ดึงให้ครบชุด:
    บริษัทสหรัฐ  : 10-K x2, 10-Q x4, 8-K x6 (+ ใบแนบ EX-99 = ข่าวผลประกอบการ/สไลด์), DEF 14A x1
    บริษัทต่างชาติ: 20-F x2, 6-K x6 (+ EX-99)            [สลับให้อัตโนมัติ]
    + companyfacts.json = ตัวเลขงบทุกตัวที่บริษัทเคยรายงาน แบบมีโครงสร้าง (XBRL)

ใช้ Python มาตรฐานล้วน ไม่ต้องติดตั้งอะไรเพิ่ม

SEC บังคับให้ระบุชื่อ+อีเมลจริงใน User-Agent ไม่งั้นบล็อก:
    SEC_CONTACT="Your Name you@email.com"

ตัวอย่าง:
    python fetch_us.py NVDA --out ./data/NVDA
    python fetch_us.py TSM  --out ./data/TSM --contact "Jane Doe jane@x.com"
    python fetch_us.py AAPL --quarters 6 --events 8
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# คอนโซล Windows ค่าเริ่มต้นพิมพ์ภาษาไทยไม่ได้ — บังคับเป็น UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{doc}"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/index.json"

EXHIBIT_FORMS = {"8-K", "6-K"}


def get(url: str, ua: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    time.sleep(0.2)  # SEC ขอไม่เกิน 10 ครั้ง/วินาที
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        import gzip
        data = gzip.decompress(data)
    return data


def resolve_cik(ticker: str, ua: str):
    raw = json.loads(get(TICKERS_URL, ua))
    t = ticker.upper()
    for row in raw.values():
        if row.get("ticker", "").upper() == t:
            return str(row["cik_str"]).zfill(10), row.get("title", "")
    raise SystemExit(f"ไม่พบ ticker {ticker!r} ในทะเบียนของ SEC")


def pick_filings(recent: dict, plan: dict):
    forms, accns = recent["form"], recent["accessionNumber"]
    dates, docs = recent["filingDate"], recent["primaryDocument"]
    seen, counts, out = set(), {k: 0 for k in plan}, []
    for i in range(len(forms)):
        form = forms[i]
        if form not in plan or counts[form] >= plan[form]:
            continue
        if accns[i] in seen:
            continue
        seen.add(accns[i])
        counts[form] += 1
        out.append({"form": form, "accn": accns[i],
                    "date": dates[i], "doc": docs[i]})
    return out


def fetch_exhibits(cik: str, accn_nodash: str, ua: str, primary_doc: str = ""):
    """คืน [(ชื่อไฟล์, ป้าย)] ของใบแนบ EX-99 (ข่าวผลประกอบการ/สไลด์)"""
    try:
        idx = json.loads(get(INDEX_URL.format(cik=cik, accn=accn_nodash), ua))
    except Exception as e:
        print(f"    (อ่าน index.json ไม่ได้: {e})", file=sys.stderr)
        return []
    readable = (".htm", ".html", ".pdf", ".txt")
    ex99, other = [], []
    for it in idx.get("directory", {}).get("item", []):
        typ = (it.get("type") or "").upper().strip()
        name = (it.get("name") or "").strip()
        if not name or name == primary_doc:
            continue
        if os.path.splitext(name)[1].lower() not in readable:
            continue
        low = name.lower()
        if ("99" in typ) or ("ex99" in low) or ("ex-99" in low):
            ex99.append((name, typ or "EX-99"))
        elif typ.startswith("EX-") and not typ.startswith(("EX-101", "EX-104")):
            other.append((name, typ))
    return ex99 if ex99 else other


def save_facts(cik10: str, ua: str, out_dir: Path):
    """XBRL companyfacts = ตัวเลขงบทุกตัวที่เคยรายงาน มีโครงสร้างพร้อมใช้
    ไม่ต้องแกะ HTML ไม่มีทางอ่านเลขผิด"""
    try:
        raw = get(FACTS_URL.format(cik10=cik10), ua)
    except Exception as e:
        print(f"  ข้าม companyfacts ({e})", file=sys.stderr)
        return None
    p = out_dir / "companyfacts.json"
    p.write_bytes(raw)
    try:
        d = json.loads(raw)
        tags = sum(len(v) for v in d.get("facts", {}).values())
        print(f"  saved companyfacts.json  ({len(raw)//1024} KB · {tags} รายการบัญชี)")
        idx = out_dir / "companyfacts_index.txt"
        lines = ["ดัชนีรายการบัญชีใน companyfacts.json",
                 "(ใช้ค้นว่ามีตัวเลขอะไรให้ใช้บ้าง ก่อนเปิดไฟล์ JSON ก้อนใหญ่)", ""]
        for tax, items in sorted(d.get("facts", {}).items()):
            lines.append(f"== {tax} ({len(items)} รายการ) ==")
            for tag, meta in sorted(items.items()):
                lines.append(f"  {tag}\t{meta.get('label') or ''}")
            lines.append("")
        idx.write_text("\n".join(lines), encoding="utf-8")
        print(f"  saved companyfacts_index.txt  (ดัชนีชื่อรายการ อ่านง่ายกว่า)")
    except Exception:
        pass
    return p


def main() -> int:
    ap = argparse.ArgumentParser(
        description="ดึงเอกสารต้นฉบับของหุ้นสหรัฐจาก SEC EDGAR")
    ap.add_argument("ticker")
    ap.add_argument("--out", default=None, help="โฟลเดอร์ปลายทาง (ค่าเริ่มต้น ./data/<TICKER>)")
    ap.add_argument("--contact", default=os.environ.get("SEC_CONTACT", ""),
                    help='ชื่อ+อีเมลสำหรับ User-Agent เช่น "Jane Doe jane@x.com"')
    ap.add_argument("--annuals", type=int, default=2)
    ap.add_argument("--quarters", type=int, default=4)
    ap.add_argument("--events", type=int, default=6)
    ap.add_argument("--no-exhibits", action="store_true")
    ap.add_argument("--no-facts", action="store_true", help="ข้าม companyfacts (XBRL)")
    args = ap.parse_args()

    contact = args.contact.strip()
    if not contact:
        print("ERROR: ต้องระบุอีเมลจริง — SEC บังคับ\n"
              '  ตั้ง SEC_CONTACT="Your Name you@email.com" หรือใช้ --contact',
              file=sys.stderr)
        return 2
    ua = f"stock-deepdive/1.0 ({contact})"

    ticker = args.ticker.upper()
    out_dir = Path(args.out) if args.out else Path("data") / ticker
    out_dir.mkdir(parents=True, exist_ok=True)

    cik10, title = resolve_cik(ticker, ua)
    cik = str(int(cik10))
    print(f"{ticker} -> CIK {cik10} ({title})")

    if not args.no_facts:
        save_facts(cik10, ua, out_dir)

    sub = json.loads(get(SUBMISSIONS_URL.format(cik10=cik10), ua))
    recent = sub["filings"]["recent"]

    domestic = {"10-K": args.annuals, "10-Q": args.quarters,
                "8-K": args.events, "DEF 14A": 1}
    foreign = {"20-F": args.annuals, "6-K": max(args.events, args.quarters)}

    picks = pick_filings(recent, domestic)
    if not any(p["form"] in ("10-K", "10-Q") for p in picks):
        print("ไม่พบ 10-K/10-Q — ลองแบบบริษัทต่างชาติ (20-F / 6-K)...")
        picks = pick_filings(recent, foreign)
    if not picks:
        raise SystemExit("ไม่พบเอกสารที่รองรับ (10-K/10-Q/8-K/DEF 14A/20-F/6-K)")

    n = 0
    for f in picks:
        accn_nodash = f["accn"].replace("-", "")
        url = ARCHIVE_URL.format(cik=cik, accn=accn_nodash, doc=f["doc"])
        ext = os.path.splitext(f["doc"])[1] or ".htm"
        fname = f"{f['form'].replace('/', '-')}_{f['date']}_{accn_nodash}{ext}"
        try:
            (out_dir / fname).write_bytes(get(url, ua))
            n += 1
            print(f"  saved {f['form']:8s} {f['date']}  ->  {fname}")
        except Exception as e:
            print(f"  FAILED {f['form']} {f['date']}: {e}", file=sys.stderr)

        if f["form"] in EXHIBIT_FORMS and not args.no_exhibits:
            for exname, extype in fetch_exhibits(cik, accn_nodash, ua, f["doc"]):
                exurl = ARCHIVE_URL.format(cik=cik, accn=accn_nodash, doc=exname)
                exext = os.path.splitext(exname)[1] or ".htm"
                safetype = (extype or "EX").replace(".", "").replace("/", "-").replace(" ", "")
                exfn = f"{f['form'].replace('/', '-')}_{f['date']}_{accn_nodash}_{safetype}{exext}"
                try:
                    (out_dir / exfn).write_bytes(get(exurl, ua))
                    n += 1
                    print(f"    + ใบแนบ {extype:10s} ->  {exfn}")
                except Exception as e:
                    print(f"    FAILED ใบแนบ {extype}: {e}", file=sys.stderr)

    print(f"\nเสร็จ — {n} ไฟล์ใน {out_dir}/")
    print("\n" + "=" * 62)
    print("สิ่งที่ EDGAR ไม่มี — ถ้าต้องการต้องหาเองจากหน้านักลงทุนสัมพันธ์:")
    print("  [ ] บทถอดเทปประชุมนักลงทุนฉบับเต็ม")
    print("  [ ] สไลด์นำเสนอนักลงทุน (ถ้าไม่ได้ติดมากับใบแนบ 8-K ข้างบน)")
    print("  [ ] จดหมายถึงผู้ถือหุ้น")
    print("ของคนอื่นวิเคราะห์ (บทวิเคราะห์ ข่าว คลิป) = ไม่ใช่ต้นฉบับ ใช้เป็นเบาะแสเท่านั้น")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
