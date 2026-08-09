#!/usr/bin/env python3
"""
check_numbers.py — ตรวจว่าตัวเลขทุกตัวในรายงาน สาวกลับไปถึง FACTS.md ได้จริงไหม

แทนที่จะให้ agent เปิดเอกสารต้นฉบับไล่ตรวจตัวเลขทีละตัวทั่วทั้งรายงาน (ช้าและแพง)
ระบบใหม่บังคับว่า **ตัวเลขเข้ารายงานได้ทางเดียวคือผ่าน FACTS.md**
สคริปต์นี้จึงตรวจแค่ว่ารายงานไม่ได้หลุดออกนอก FACTS — ใช้เวลาไม่กี่วินาที
ส่วนความถูกต้องของ FACTS.md เองเป็นหน้าที่ของ agent factcheck ซึ่งตรวจครั้งเดียวจบ

การเทียบยอมให้ปัดเศษและเปลี่ยนหน่วยได้ เช่น รายงานเขียน "1,197 ล้านบาท"
ขณะที่ FACTS เก็บ 1196589 (พันบาท) ⇒ ถือว่าตรงกัน

ตัวเลขที่คำนวณขึ้นเอง (อัตราส่วน ผลต่าง ร้อยละ) ให้เขียนกำกับ `[คำนวณ]` ไว้ในบรรทัดนั้น
สคริปต์จะข้ามให้ — แต่บรรทัดพวกนั้นต้องแสดงวิธีคิดให้เห็น

ตัวอย่าง:
    python check_numbers.py ./deepdive/DITTO-2026-08-09.md ./deepdive/DITTO-FACTS.md
    python check_numbers.py report.md FACTS.md --strict     # ออกด้วยรหัส 1 ถ้าเจอตัวหลุด
"""
import argparse
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        if (_s.encoding or "").lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
CALC_MARK = "[คำนวณ]"
SCALES = (1, 1e3, 1e-3, 1e6, 1e-6)
REL_TOL = 0.006          # ยอมให้คลาดเคลื่อนจากการปัดเศษ 0.6%
MIN_MAGNITUDE = 100      # ต่ำกว่านี้และไม่มีลูกน้ำ = เลขหัวข้อ/ลำดับ ไม่ใช่ข้อมูลการเงิน


def parse_nums(text: str):
    out = []
    for m in NUM.finditer(text):
        raw = m.group()
        try:
            out.append((raw, float(raw.replace(",", ""))))
        except ValueError:
            continue
    return out


def is_noise(raw: str, val: float) -> bool:
    """เลขที่ไม่ต้องตรวจ — ลำดับหัวข้อ ปี พ.ศ./ค.ศ. และจำนวนเล็กที่ไม่ใช่ตัวเงิน"""
    a = abs(val)
    if "," not in raw and a < MIN_MAGNITUDE:
        return True
    if "," not in raw and "." not in raw:
        if 1900 <= a <= 2100 or 2400 <= a <= 2700:   # ปี ค.ศ. และ พ.ศ.
            return True
    return False


def matches(val: float, facts: list) -> bool:
    for s in SCALES:
        t = val * s
        tol = max(abs(t) * REL_TOL, 1.0)
        for f in facts:
            if abs(t - f) <= tol:
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(
        description="ตรวจว่าตัวเลขในรายงานสาวกลับไปถึง FACTS.md ได้")
    ap.add_argument("report", help="ไฟล์รายงาน .md")
    ap.add_argument("facts", help="ไฟล์ FACTS.md")
    ap.add_argument("--strict", action="store_true",
                    help="ออกด้วยรหัส 1 ถ้ามีตัวเลขหลุด")
    ap.add_argument("--out", default=None, help="เขียนผลเป็นไฟล์ .md")
    args = ap.parse_args()

    rp, fp = Path(args.report), Path(args.facts)
    for p in (rp, fp):
        if not p.is_file():
            print(f"ไม่พบไฟล์: {p}", file=sys.stderr)
            return 2

    facts = [v for _, v in parse_nums(fp.read_text(encoding="utf-8"))]
    if not facts:
        print(f"⚠️  ไม่พบตัวเลขใน {fp.name} เลย — ตรวจต่อไม่ได้", file=sys.stderr)
        return 2

    orphans, checked, skipped_calc = [], 0, 0
    for i, line in enumerate(rp.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if s.startswith("#") or s.startswith("|---") or not s:
            continue
        if CALC_MARK in line:
            skipped_calc += 1
            continue
        for raw, val in parse_nums(line):
            if is_noise(raw, val):
                continue
            checked += 1
            if not matches(val, facts):
                ctx = re.sub(r"\s+", " ", s)
                orphans.append((i, raw, ctx[:110] + ("…" if len(ctx) > 110 else "")))

    pct = 100 * (checked - len(orphans)) / checked if checked else 100.0
    head = [
        f"# ผลตรวจตัวเลข — {rp.name}",
        "",
        f"- เทียบกับ: `{fp.name}` ({len(facts):,} ตัวเลข)",
        f"- ตรวจแล้ว: **{checked:,} ตัว** · สาวกลับได้ **{checked - len(orphans):,}** "
        f"({pct:.1f}%) · **หลุด {len(orphans):,}**",
        f"- ข้ามบรรทัดที่กำกับ `{CALC_MARK}` ไว้: {skipped_calc:,} บรรทัด",
        "",
        "> ⚠️ นี่คือ**ตะแกรงกันตัวเลขหลุด ไม่ใช่การพิสูจน์ว่าถูก** — การเทียบยอมให้เปลี่ยนหน่วย",
        "> และปัดเศษ ยิ่ง FACTS.md ใหญ่ ยิ่งมีโอกาสไปพ้องกับตัวเลขที่ไม่เกี่ยวกัน",
        "> ให้ FACTS.md เก็บเฉพาะตัวเลขที่ใช้จริง (ราว 100-150 ตัว) ความถูกต้องของตัว FACTS เอง",
        "> เป็นหน้าที่ของ agent factcheck",
        "",
    ]
    if orphans:
        head += [
            "## ตัวเลขที่หาต้นทางใน FACTS.md ไม่เจอ",
            "",
            "อย่างใดอย่างหนึ่ง: ต้องเพิ่มเข้า FACTS.md พร้อมแหล่งที่มา · "
            f"กำกับ `{CALC_MARK}` แล้วแสดงวิธีคิด · หรือเอาออกจากรายงาน",
            "",
            "| บรรทัด | ตัวเลข | บริบท |",
            "|---:|---|---|",
        ]
        head += [f"| {ln} | `{raw}` | {ctx} |" for ln, raw, ctx in orphans]
    else:
        head.append("✅ ทุกตัวเลขสาวกลับไปถึง FACTS.md ได้")

    text = "\n".join(head) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"เขียนผลไว้ที่ {args.out}")
    print(f"ตรวจ {checked:,} ตัว · หลุด {len(orphans):,} ตัว ({pct:.1f}% สาวกลับได้)")
    for ln, raw, ctx in orphans[:15]:
        print(f"  บรรทัด {ln}: {raw}  — {ctx[:70]}")
    if len(orphans) > 15:
        print(f"  ... และอีก {len(orphans) - 15} ตัว")

    return 1 if (args.strict and orphans) else 0


if __name__ == "__main__":
    raise SystemExit(main())
