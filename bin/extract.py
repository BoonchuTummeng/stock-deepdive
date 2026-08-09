#!/usr/bin/env python3
"""
extract.py — เตรียมเอกสารดิบใน data/<TICKER>/ ให้พร้อมอ่าน ก่อนส่งให้ agent

ทำสามอย่างที่เดิม agent ต้องเสียเวลาทำเอง ทั้งที่ผลลัพธ์เหมือนกันทุกครั้ง:

  1. แปลง .docx/.xlsx ใหม่ทั้งหมด โดย **แกะตาราง Excel ที่ฝังในหมายเหตุประกอบงบ**
     (ตัวแปลงรุ่นเก่าทิ้งตารางพวกนี้ไปหมด ซึ่งคือที่ที่ตัวเลขสำคัญอยู่)
  2. แปลง PDF (56-1 One Report) เป็นข้อความพร้อมหมายเลขหน้า `[[หน้า N]]`
     เพื่อให้อ้างอิงกลับได้ และให้ agent กระโดดอ่านเฉพาะหน้าที่ต้องการ
  3. ตรวจว่าหน้าไหนของ PDF เป็น **ภาพสแกนที่ไม่มีข้อความ** แล้วแจ้งไว้ใน MANIFEST
     — รายงานผู้สอบบัญชีมักถูกพิมพ์ซ้ำเป็นภาพแบบนี้ ต้องเปิดอ่านด้วยสายตา

ผลลัพธ์: `<โฟลเดอร์>/MANIFEST.md` = สารบัญว่ามีอะไรอ่านได้บ้าง อยู่ไฟล์ไหน กี่ตัวอักษร
         และอะไรที่ยังอ่านไม่ได้เพราะอะไร

ต้องมี: Python 3.9+ (ส่วนแปลง Office ใช้ไลบรารีมาตรฐานล้วน)
ไม่บังคับ: pymupdf หรือ pypdf — มีเมื่อต้องอ่าน PDF เช่นแบบ 56-1 One Report
          ถ้าไม่มี สคริปต์จะข้ามเฉพาะส่วน PDF แล้วบอกว่าข้ามอะไร

ตัวอย่าง:
    python extract.py ./data/DITTO
    python extract.py ./data/DITTO --no-pdf     # ข้าม PDF (เร็วขึ้นมาก)
"""
import argparse
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_th import docx_to_text, xlsx_to_text  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# หน้าสแกนมักไม่ได้ว่างสนิท — ยังมีเลขหน้า หัวกระดาษ หรือลายน้ำเป็นข้อความจริงติดมา
# (56-1 ของ DITTO หน้าสแกนมี 38-108 ตัวอักษร) เกณฑ์ตายตัวจึงจับไม่ได้
# ต้องเทียบกับค่ากลางของเอกสารนั้นเอง แล้วมีพื้นขั้นต่ำกันเอกสารที่บางทั้งเล่ม
SCAN_REL = 0.15      # สั้นกว่า 15% ของค่ากลาง = น่าจะเป็นภาพ
SCAN_FLOOR = 150     # และต้องสั้นกว่านี้ด้วย จึงจะนับ


def _pdf_pages(path: Path):
    """คืน (รายการข้อความรายหน้า, ข้อความบอกปัญหาถ้ามี)

    ลอง PyMuPDF ก่อนเพราะเร็วกว่าและแยกคอลัมน์ดีกว่า ถ้าไม่มีค่อยใช้ pypdf
    ถ้าไม่มีทั้งคู่ ให้บอกตรง ๆ ว่าต้องติดตั้งอะไร ไม่ใช่ปล่อยผ่านเงียบ ๆ"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        pass
    else:
        try:
            with fitz.open(path) as doc:
                return [pg.get_text() or "" for pg in doc], None
        except Exception as e:
            return [], f"PyMuPDF เปิดไฟล์ไม่ได้: {e}"

    try:
        from pypdf import PdfReader
    except ImportError:
        return [], ("ไม่มีไลบรารีอ่าน PDF ในเครื่องนี้ — "
                    "ติดตั้งอย่างใดอย่างหนึ่ง:  pip install pymupdf   หรือ   pip install pypdf")
    try:
        return [pg.extract_text() or "" for pg in PdfReader(str(path)).pages], None
    except Exception as e:
        return [], f"pypdf เปิดไฟล์ไม่ได้: {e}"


def pdf_to_text(path: Path):
    """คืน (ข้อความพร้อมหมายเลขหน้า, จำนวนหน้า, [หน้าที่เป็นภาพสแกน], ข้อความปัญหา)"""
    pages, err = _pdf_pages(path)
    if err:
        return f"[อ่าน PDF ไม่ได้ — {err}]", 0, [], err

    lens = [len(t.strip()) for t in pages]
    cut = min(SCAN_FLOOR, statistics.median(lens) * SCAN_REL) if lens else 0
    scanned = [i + 1 for i, n in enumerate(lens) if n < cut]
    sset = set(scanned)
    body = "\n".join(
        f"\n[[หน้า {i + 1}]]" + ("  ⟨ภาพสแกน — ข้อความไม่ครบ⟩" if i + 1 in sset else "")
        + f"\n{t}" for i, t in enumerate(pages))
    return body, len(pages), scanned, None


def ranges(nums):
    """[3,4,5,9] -> '3-5, 9' — ย่อรายการหน้าให้อ่านออก"""
    if not nums:
        return ""
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:] + [None]:
        if n != prev + 1:
            out.append(str(start) if start == prev else f"{start}-{prev}")
            start = n
        prev = n
    return ", ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="เตรียมเอกสารดิบให้พร้อมอ่าน")
    ap.add_argument("folder", help="โฟลเดอร์เอกสาร เช่น ./data/DITTO")
    ap.add_argument("--no-pdf", action="store_true", help="ข้ามการแปลง PDF")
    args = ap.parse_args()

    root = Path(args.folder)
    if not root.is_dir():
        print(f"ไม่พบโฟลเดอร์: {root}", file=sys.stderr)
        return 1

    rows, notes_warn, scan_notes, pdf_warn = [], [], [], []
    n_office = n_pdf = 0

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        low, rel = p.name.lower(), p.relative_to(root).as_posix()

        if low.endswith((".docx", ".xlsx")):
            txt = docx_to_text(p) if low.endswith(".docx") else xlsx_to_text(p)
            out = p.with_suffix(".txt")
            out.write_text(txt, encoding="utf-8")
            n_office += 1
            tables = txt.count("----- ตารางฝัง")
            rows.append((rel, out.relative_to(root).as_posix(), len(txt),
                         f"ตารางฝัง {tables} ตาราง" if tables else ""))

        elif low.endswith(".pdf") and not args.no_pdf:
            txt, pages, scanned, pdf_err = pdf_to_text(p)
            out = p.with_suffix(".txt")
            out.write_text(txt, encoding="utf-8")
            n_pdf += 1
            note = f"{pages} หน้า" if not pdf_err else "อ่านไม่ได้"
            if pdf_err:
                pdf_warn.append(pdf_err)
            if scanned:
                note += f" · เป็นภาพสแกน {len(scanned)} หน้า: {ranges(scanned)}"
                scan_notes.append((rel, ranges(scanned)))
            rows.append((rel, out.relative_to(root).as_posix(), len(txt), note))

        elif low.endswith((".doc", ".xls")):
            notes_warn.append(rel)

    lines = [
        f"# สารบัญเอกสาร — {root.name}",
        "",
        f"สร้างโดย `extract.py` เมื่อ {date.today().isoformat()}",
        "",
        "ไฟล์ `.txt` ทุกไฟล์ด้านล่างคือฉบับที่แปลงแล้ว **อ่านไฟล์นี้ ไม่ต้องไปแกะไฟล์ดิบเอง**",
        "",
        "| ไฟล์ต้นทาง | ไฟล์ที่อ่านได้ | ตัวอักษร | หมายเหตุ |",
        "|---|---|---:|---|",
    ]
    for src, dst, size, note in rows:
        lines.append(f"| `{src}` | `{dst}` | {size:,} | {note} |")

    if scan_notes:
        lines += [
            "",
            "## 🔴 หน้าที่เป็นภาพสแกน — ข้อความว่าง ต้องเปิดอ่านด้วยสายตา",
            "",
            "ใช้ Read tool ชี้ที่ไฟล์ **PDF** (ไม่ใช่ .txt) แล้วระบุ `pages` ครั้งละไม่เกิน 20 หน้า",
            "",
        ]
        for rel, rng in scan_notes:
            lines.append(f"- `{rel}` หน้า {rng}")
        lines += [
            "",
            "รายงานผู้สอบบัญชีมักถูกพิมพ์ซ้ำเป็นภาพแบบนี้ใน 56-1 — "
            "ถ้าไฟล์ `AUDITOR_REPORT.DOC` เปิดไม่ได้ ให้มาหาในหน้าพวกนี้ก่อนจะสรุปว่าไม่มี",
        ]

    if notes_warn:
        lines += [
            "",
            "## ไฟล์ที่แปลงเป็นข้อความไม่ได้",
            "",
            "รูปแบบ Word/Excel รุ่นเก่า (.doc/.xls) เป็นไบนารี ไม่ใช่ zip+XML",
            "",
        ]
        for rel in notes_warn:
            lines.append(f"- `{rel}`")

    (root / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"แปลงแล้ว: Office {n_office} ไฟล์ · PDF {n_pdf} ไฟล์")
    for w in dict.fromkeys(pdf_warn):
        print(f"⚠️  {w}")
    if scan_notes:
        print(f"⚠️  พบหน้าที่เป็นภาพสแกน {len(scan_notes)} ไฟล์ — ดูรายละเอียดใน MANIFEST.md")
    if notes_warn:
        print(f"⚠️  แปลงไม่ได้ {len(notes_warn)} ไฟล์ (.doc/.xls รุ่นเก่า)")
    print(f"สารบัญ: {root / 'MANIFEST.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
