"""국어 임용 기출 PDF → data/questions.js + pages/*.jpg

사용법 (study_02 폴더에서):
    py -P -E tools/build.py

pdf/ 폴더에 '2027_중등1차_국어_전공A.pdf'처럼
'연도 ... 전공A/B' 가 들어간 이름으로 PDF를 넣고 다시 실행하면 됩니다.
필요한 라이브러리: py -m pip install --user pdfplumber pypdfium2
"""
import json
import pathlib
import re

import pdfplumber
import pypdfium2 as pdfium

ROOT = pathlib.Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdf"
PAGE_DIR = ROOT / "pages"
OUT = ROOT / "data" / "questions.js"

JUNK = [
    r"^\d{4}학년도 중등학교교사$",
    r"^국$",
    r"^어$",
    r"^수험 번호",
    r"^제1차 시험",
    r"^◦ 문제지 전체",
    r"^◦ 모든 문항에는",
    r"^임용후보자 선정경쟁시험$",
    r"^성 명 :",
    r"^\d+문항 \d+점",
    r"^국 어 \[전공 ?[AB]\]$",
    r"^\] \(8면 중 면\)$",
    r"^\d$",
    r"^<수고하셨습니다\.>$",
]
JUNK_RE = [re.compile(p) for p in JUNK]
START_RE = re.compile(r"^(\d{1,2})\.\s")
PTS_RE = re.compile(r"\[\d{1,2}점\]")


def clean_line(s: str) -> str:
    s = re.sub(r"\(cid:\d+\)", "□", s)
    s = s.replace("​", "")
    return s.rstrip()


U0, U1 = "", ""  # 밑줄 시작/끝 표시 (화면에서 <u>로 바뀜)


def underline_segments(page):
    """글자 아래 가로선(밑줄). 상자 테두리(세로선과 맞닿은 선)와 쪽 머리·꼬리선은 뺀다."""
    vs = [o for o in page.lines if abs(o["x0"] - o["x1"]) < 1.5]
    segs = []
    for o in page.lines:
        if abs(o["top"] - o["bottom"]) >= 1.5 or not 3 <= o["x1"] - o["x0"] <= 400:
            continue
        y = o["top"]
        edge = any((abs(v["x0"] - o["x0"]) < 2 or abs(v["x0"] - o["x1"]) < 2) and v["top"] - 2 <= y <= v["bottom"] + 2 for v in vs)
        if not edge:
            segs.append(o)
    return segs


def mark_underlines(page):
    segs = underline_segments(page)
    n = 0
    for c in page.chars:
        if not c["text"].strip():
            continue
        cx = (c["x0"] + c["x1"]) / 2
        if any(o["x0"] - 1 <= cx <= o["x1"] + 1 and -1.5 <= o["top"] - c["bottom"] <= 3 for o in segs):
            c["text"] = U0 + c["text"] + U1
            n += 1
    return n


def tidy_marks(ln):
    ln = re.sub(U1 + r"(\s*)" + U0, r"\1", ln)  # 이어지는 밑줄 글자는 한 덩어리로
    return ln


def extract(pdf_path: pathlib.Path):
    """Return list of (page_no, line) in reading order (left column, then right)."""
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            w, h = page.width, page.height
            mark_underlines(page)
            for box in ((0, 0, w / 2, h), (w / 2, 0, w, h)):
                t = page.crop(box).extract_text(x_tolerance=1.5) or ""
                for ln in t.splitlines():
                    ln = tidy_marks(clean_line(ln))
                    plain = ln.replace(U0, "").replace(U1, "").strip()
                    if not plain or any(r.search(plain) for r in JUNK_RE):
                        continue
                    lines.append((i, ln))
    return lines


SEC_RE = re.compile(r"^(기입형|서술형|논술형)\s*【")


def split_questions(lines):
    """차례에 맞는 번호('n.')로 시작하고, 몇 줄 안에 배점 표시([n점])가 있으면 새 문항.
    2014~2016학년도처럼 '서술형 【1 ~ 6】' 구역마다 번호가 다시 시작하는 경우도 처리한다."""
    qs, cur, expect, sec = [], None, 1, ""
    for idx, (page, ln) in enumerate(lines):
        sm = SEC_RE.match(ln.strip())
        if sm:
            sec, expect = sm.group(1), 1
            continue
        m = START_RE.match(ln.strip())
        if m and int(m.group(1)) == expect:
            ahead = " ".join(l for _, l in lines[idx:idx + 7])
            if not PTS_RE.search(ahead):
                m = None
        if m and int(m.group(1)) == expect:
            cur = {"no": len(qs) + 1, "orig": expect, "sec": sec, "pages": [page], "lines": []}
            qs.append(cur)
            expect += 1
            ln = ln.strip()[len(m.group(1)) + 1:].strip()
        if cur is None:
            continue
        if page not in cur["pages"]:
            cur["pages"].append(page)
        cur["lines"].append(ln)
    return qs


def render(pdf_path, key):
    PAGE_DIR.mkdir(exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    for i in range(len(pdf)):
        out = PAGE_DIR / f"{key}-{i + 1}.jpg"
        if out.exists():
            continue
        pdf[i].render(scale=1.6).to_pil().convert("RGB").save(out, quality=78, optimize=True)


def main():
    result = []
    for pdf_path in sorted(PDF_DIR.glob("*.pdf")):
        m = re.search(r"(\d{4}).*?(?:전공|국어)\s*([AB])", pdf_path.stem)
        if not m:
            print("건너뜀(이름에 연도/전공A·B 없음):", pdf_path.name)
            continue
        year, paper = int(m.group(1)), m.group(2)
        key = f"{year}{paper}"
        render(pdf_path, key)
        for q in split_questions(extract(pdf_path)):
            body = "\n".join(q["lines"]).strip()
            pts = re.search(r"\[(\d{1,2})점\]", body)
            result.append({
                "id": f"{key}-{q['no']}",
                "year": year,
                "paper": paper,
                "no": q["no"],
                "label": (q["sec"] + " " if q["sec"] else "") + f"{q['orig']}번",
                "points": int(pts.group(1)) if pts else None,
                "pages": [f"pages/{key}-{p}.jpg" for p in q["pages"]],
                "pdf": f"pdf/{pdf_path.name}",
                "text": body,
            })
        print(key, "문항", sum(1 for r in result if r["id"].startswith(key + "-")))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        "// tools/build.py 가 자동으로 만든 파일입니다. 직접 고치지 마세요.\n"
        "window.QUESTIONS = " + json.dumps(result, ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8",
    )
    print("총", len(result), "문항 →", OUT)


if __name__ == "__main__":
    main()
