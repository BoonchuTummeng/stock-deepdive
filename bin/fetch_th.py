#!/usr/bin/env python3
"""
fetch_th.py — ดึงงบการเงินหุ้นไทยจากระบบ iDisc ของสำนักงาน ก.ล.ต.

iDisc เป็นแหล่งเดียวที่ให้ **หมายเหตุประกอบงบ** ฟรี ไม่ต้อง login และไม่ติด Cloudflare
ในไฟล์ zip แต่ละงวดมีโครงเดิมเสมอ:
    AUDITOR_REPORT.docx     รายงานผู้สอบบัญชี
    FINANCIAL_STATEMENTS.xlsx  งบดุล/กำไรขาดทุน/กระแสเงินสด พร้อมงวดเทียบ
    NOTES.docx              หมายเหตุประกอบงบ  <- จุดที่ความจริงซ่อนอยู่

สคริปต์นี้จะแตก zip ให้ แล้ว **แปลงเป็นข้อความธรรมดา** ด้วย Python มาตรฐานล้วน
(ทั้ง .docx และ .xlsx คือไฟล์ zip ที่ข้างในเป็น XML จึงอ่านได้โดยไม่ต้องลงไลบรารีเพิ่ม)

⚠️ iDisc ปฏิเสธ User-Agent แบบทั่วไปเช่น "Mozilla/5.0" — ต้องใส่ที่ระบุตัวตนได้
⚠️ ชื่อย่อหุ้นอาจชนกับบริษัทที่ออกหุ้นกู้แต่ไม่ได้จดทะเบียน — สคริปต์จะพิมพ์ชื่อบริษัทที่เจอ
   ให้ตรวจก่อนเสมอว่าใช่ตัวที่ต้องการ

ตัวอย่าง:
    python fetch_th.py DITTO --out ./data/DITTO
    python fetch_th.py NETBAY --periods 8
    python fetch_th.py THANI --no-text     # เอาแค่ไฟล์ดิบ ไม่ต้องแปลงข้อความ
"""
import argparse
import io
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# คอนโซล Windows ค่าเริ่มต้นพิมพ์ภาษาไทยไม่ได้ — บังคับเป็น UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

INDEX_FS = "https://market.sec.or.th/public/idisc/en/Viewmore/fs-full?searchSymbol={sym}"
INDEX_561 = "https://market.sec.or.th/public/idisc/en/Viewmore/fs-r561?searchSymbol={sym}"
DOWNLOAD = "https://market.sec.or.th/public/idisc/Download?FILEID={fid}"

UA = "stock-deepdive/1.0 (equity research; contact via plugin repo)"
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
X_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
O_NS = "{urn:schemas-microsoft-com:office:office}"
PKG_R_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def get(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    time.sleep(0.4)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def find_company(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def find_zips(html: str):
    """คืน FILEID ของไฟล์ zip เรียงจากใหม่ไปเก่า ตัดตัวซ้ำออก"""
    ids = re.findall(r"FILEID=([^\"'&<>\s]+\.zip)", html)
    out, seen = [], set()
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def label_from_fileid(fid: str) -> str:
    """dat/news/202605/1640FIN150520261641510463E.zip -> 202605_1640FIN15052026"""
    m = re.search(r"/(\d{6})/([^/]+)\.zip$", fid)
    if not m:
        return re.sub(r"\W+", "_", fid)[-30:]
    return f"{m.group(1)}_{m.group(2)[:20]}"


# ── แปลงเป็นข้อความ (ไม่ต้องลงไลบรารีเพิ่ม) ───────────────────────────
def _xlsx_sheets(z: zipfile.ZipFile):
    """คืน [(ชื่อชีต, [[เซลล์, ...], ...]), ...] จาก xlsx ที่เปิดเป็น ZipFile แล้ว"""
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.iter(f"{X_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{X_NS}t")))

    names = {}
    if "xl/workbook.xml" in z.namelist():
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        for i, sh in enumerate(wb.iter(f"{X_NS}sheet"), start=1):
            names[f"sheet{i}.xml"] = sh.get("name", f"sheet{i}")

    out = []
    for s in sorted(n for n in z.namelist()
                    if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")):
        rows = []
        root = ET.fromstring(z.read(s))
        for row in root.iter(f"{X_NS}row"):
            cells = []
            for c in row.iter(f"{X_NS}c"):
                v = c.find(f"{X_NS}v")
                txt = ""
                if v is not None and v.text is not None:
                    if c.get("t") == "s":
                        try:
                            txt = shared[int(v.text)]
                        except (ValueError, IndexError):
                            txt = v.text
                    else:
                        txt = v.text
                else:
                    is_el = c.find(f"{X_NS}is")
                    if is_el is not None:
                        txt = "".join(t.text or "" for t in is_el.iter(f"{X_NS}t"))
                cells.append((txt or "").strip())
            while cells and not cells[-1]:
                cells.pop()
            if cells:
                rows.append(cells)
        out.append((names.get(s.split("/")[-1], s.split("/")[-1]), rows))
    return out


def xlsx_to_text(path: Path) -> str:
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        return f"[แปลงไม่ได้: {e}]"
    chunks = []
    for title, rows in _xlsx_sheets(z):
        chunks.append(f"\n===== ชีต: {title} =====")
        chunks.extend("\t".join(r) for r in rows)
    return "\n".join(chunks)


def _para_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(f"{W_NS}t")).strip()


def _table_lines(tbl) -> list:
    """<w:tbl> -> บรรทัดคั่น tab · เก็บโครงแถว/คอลัมน์ไว้ ไม่ให้เซลล์แตกเป็นบรรทัดละตัว"""
    lines = []
    for tr in tbl.findall(f"{W_NS}tr"):
        cells = [" ".join(x for x in (_para_text(p) for p in tc.iter(f"{W_NS}p")) if x)
                 for tc in tr.findall(f"{W_NS}tc")]
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            lines.append("\t".join(cells))
    return lines


def _docx_embed_rels(z: zipfile.ZipFile) -> dict:
    """rId -> path ของเวิร์กบุ๊กที่ฝังอยู่ใน word/embeddings/"""
    try:
        root = ET.fromstring(z.read("word/_rels/document.xml.rels"))
    except Exception:
        return {}
    out = {}
    for rel in root.iter(f"{PKG_R_NS}Relationship"):
        tgt = rel.get("Target", "")
        if "embeddings/" in tgt:
            out[rel.get("Id")] = "word/embeddings/" + tgt.split("embeddings/")[-1]
    return out


def _embedded_table_lines(z: zipfile.ZipFile, member: str, label: str) -> list:
    try:
        sub = zipfile.ZipFile(io.BytesIO(z.read(member)))
    except Exception as e:
        return [f"[ตารางฝัง {label}: แกะไม่ได้ — {e}]"]
    lines = [f"----- ตารางฝัง {label} ({member.split('/')[-1]}) -----"]
    for title, rows in _xlsx_sheets(sub):
        if not rows:
            continue
        if title and not re.fullmatch(r"(?i)sheet\d*", title):
            lines.append(f"[ชีต: {title}]")
        lines.extend("\t".join(r) for r in rows)
    lines.append("----- จบตารางฝัง -----")
    return lines


def docx_to_text(path: Path) -> str:
    """แปลง .docx เป็นข้อความ โดย **เก็บตาราง** และ **แกะเวิร์กบุ๊ก Excel ที่ฝังอยู่**
    ออกมาวางตรงตำแหน่งเดิมในเนื้อความ

    หมายเหตุประกอบงบของไทยมักเก็บตัวเลขไว้ในออบเจกต์ Excel ที่ฝังในเอกสาร
    (งบปีของบางบริษัทมีเกิน 100 ตาราง) การอ่านแค่ word/document.xml
    จะไม่เห็นตัวเลขพวกนี้เลย — ซึ่งคือจุดที่ข้อมูลสำคัญที่สุดอยู่"""
    try:
        z = zipfile.ZipFile(path)
        root = ET.fromstring(z.read("word/document.xml"))
    except Exception as e:
        return f"[แปลงไม่ได้: {e}]"

    rels = _docx_embed_rels(z)
    members = set(z.namelist())
    used, lines, n = set(), [], 0
    body = root.find(f"{W_NS}body")
    for el in (body if body is not None else root):
        if el.tag == f"{W_NS}tbl":
            lines.extend(_table_lines(el))
        elif el.tag == f"{W_NS}p":
            txt = _para_text(el)
            if txt:
                lines.append(txt)
        # ออบเจกต์ฝังโผล่ได้ทั้งในย่อหน้าและในเซลล์ตาราง
        for ole in el.iter(f"{O_NS}OLEObject"):
            member = rels.get(ole.get(f"{R_NS}id"))
            if member and member in members and member not in used:
                used.add(member)
                n += 1
                lines.extend(_embedded_table_lines(z, member, f"#{n}"))

    leftovers = sorted(m for m in members
                       if m.startswith("word/embeddings/")
                       and m.lower().endswith((".xlsx", ".xlsm"))
                       and m not in used)
    if leftovers:
        lines.append(f"\n===== ตารางฝังที่ตามตำแหน่งในเนื้อความไม่ได้ ({len(leftovers)}) =====")
        for m in leftovers:
            n += 1
            lines.extend(_embedded_table_lines(z, m, f"#{n}"))
    return "\n".join(lines)


def convert_folder(folder: Path):
    """แปลง .docx/.xlsx เป็น .txt · คืน (ไฟล์ที่แปลงได้, ไฟล์ที่แปลงไม่ได้)"""
    made, skipped = [], []
    for p in sorted(folder.iterdir()):
        low = p.name.lower()
        if low.endswith(".docx"):
            txt, out = docx_to_text(p), p.with_suffix(".txt")
        elif low.endswith(".xlsx"):
            txt, out = xlsx_to_text(p), p.with_suffix(".txt")
        elif low.endswith((".doc", ".xls")):
            # Word/Excel รูปแบบเก่า เป็นไฟล์ไบนารี ไม่ใช่ zip+XML ⇒ แปลงด้วยไลบรารีมาตรฐานไม่ได้
            skipped.append(p.name)
            continue
        else:
            continue
        out.write_text(txt, encoding="utf-8")
        made.append((out.name, len(txt)))
    return made, skipped


def main() -> int:
    ap = argparse.ArgumentParser(
        description="ดึงงบการเงินหุ้นไทยจาก iDisc ของ ก.ล.ต.")
    ap.add_argument("symbol", help="ชื่อย่อหุ้นในตลาดไทย เช่น DITTO")
    ap.add_argument("--out", default=None, help="โฟลเดอร์ปลายทาง (ค่าเริ่มต้น ./data/<SYMBOL>)")
    ap.add_argument("--periods", type=int, default=6, help="ดึงกี่งวดล่าสุด (ค่าเริ่มต้น 6)")
    ap.add_argument("--no-text", action="store_true", help="ไม่ต้องแปลงเป็นข้อความ")
    ap.add_argument("--no-561", action="store_true", help="ข้ามแบบ 56-1 One Report")
    args = ap.parse_args()

    sym = args.symbol.upper()
    out_dir = Path(args.out) if args.out else Path("data") / sym
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"ค้น iDisc: {sym}")
    try:
        html = get(INDEX_FS.format(sym=sym)).decode("utf-8", "ignore")
    except Exception as e:
        print(f"เปิดหน้าดัชนีไม่ได้: {e}", file=sys.stderr)
        return 1

    company = find_company(html)
    if company:
        print(f"  บริษัทที่ระบบเจอ: {company}")
        print("  ⚠️ ตรวจก่อนว่าใช่บริษัทที่ต้องการจริง — ชื่อย่ออาจชนกับผู้ออกหุ้นกู้ที่ไม่ได้จดทะเบียน")

    zips = find_zips(html)
    if not zips:
        print("ไม่พบไฟล์งบในหน้านี้ — อาจสะกดชื่อย่อผิด หรือบริษัทไม่ได้ยื่นผ่าน iDisc",
              file=sys.stderr)
        return 1
    print(f"  พบงบ {len(zips)} งวด — จะดึง {min(args.periods, len(zips))} งวดล่าสุด")

    got = 0
    for fid in zips[:args.periods]:
        label = label_from_fileid(fid)
        dest = out_dir / f"FS_{label}"
        dest.mkdir(parents=True, exist_ok=True)
        try:
            blob = get(DOWNLOAD.format(fid=fid))
        except Exception as e:
            print(f"  FAILED {label}: {e}", file=sys.stderr)
            continue
        zpath = dest / "package.zip"
        zpath.write_bytes(blob)
        try:
            with zipfile.ZipFile(zpath) as z:
                z.extractall(dest)
            zpath.unlink()
            inner = [p.name for p in dest.iterdir()]
            print(f"  saved {label}  ({len(blob)//1024} KB) -> {', '.join(inner)}")
            got += 1
        except Exception as e:
            print(f"  แตกไฟล์ไม่ได้ {label}: {e} (เก็บ zip ดิบไว้)", file=sys.stderr)

        if not args.no_text:
            made, skipped = convert_folder(dest)
            for name, size in made:
                print(f"      + {name}  ({size} ตัวอักษร)")
            for name in skipped:
                print(f"      ! {name} เป็นรูปแบบเก่า แปลงเป็นข้อความไม่ได้ "
                      f"(เปิดด้วย Word/LibreOffice แล้ว save เป็น .docx ถ้าจำเป็น)")

    if not args.no_561:
        print("\nดึงแบบ 56-1 One Report...")
        try:
            h2 = get(INDEX_561.format(sym=sym)).decode("utf-8", "ignore")
            ids = find_zips(h2)
            if ids:
                for fid in ids[:2]:
                    label = label_from_fileid(fid)
                    dest = out_dir / f"R561_{label}"
                    dest.mkdir(parents=True, exist_ok=True)
                    blob = get(DOWNLOAD.format(fid=fid), timeout=90)
                    zp = dest / "package.zip"
                    zp.write_bytes(blob)
                    try:
                        with zipfile.ZipFile(zp) as z:
                            z.extractall(dest)
                        zp.unlink()
                    except Exception:
                        pass
                    print(f"  saved 56-1 {label} ({len(blob)//1024} KB)")
                    if not args.no_text:
                        made, skipped = convert_folder(dest)
                        for name, size in made:
                            print(f"      + {name}  ({size} ตัวอักษร)")
                        for name in skipped:
                            print(f"      ! {name} เป็นรูปแบบเก่า แปลงไม่ได้")
            else:
                print("  ไม่พบแบบ 56-1 (บางบริษัทยื่นคนละช่องทาง)")
        except Exception as e:
            print(f"  ข้าม 56-1: {e}", file=sys.stderr)

    print(f"\nเสร็จ — งบ {got} งวดใน {out_dir}/")
    print("\n" + "=" * 62)
    print("สิ่งที่ iDisc ไม่มี — หาเพิ่มเองได้จาก:")
    print("  [ ] สไลด์ Opportunity Day  — opportunity-day.setgroup.or.th")
    print("  [ ] เว็บนักลงทุนสัมพันธ์ของบริษัท  — One Report ฉบับ PDF ย้อนหลังหลายปี")
    print("  [ ] ราคาหุ้นและมูลค่าตลาด  — iDisc ไม่มีข้อมูลราคา")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
