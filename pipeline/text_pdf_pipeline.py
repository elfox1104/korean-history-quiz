"""
텍스트 레이어가 있는 PDF(71·73·75·77회 등) 전용 추출 파이프라인.

스캔 이미지(47회)와 달리 이 PDF들은 질문·①②③④ 보기·사료가 모두
텍스트로 들어있어 OCR 없이 정확히 추출할 수 있다.

- 보기가 텍스트(①②③④)면 → 텍스트 보기(라디오)
- 보기가 사진이면(①②③④ 텍스트 없음) → 이미지+번호 버튼으로 폴백
- 질문은 텍스트, 가운데 자료/그림은 이미지로 크롭
"""
import io
import json
import re
import sys
from pathlib import Path
from typing import Optional

import fitz
import numpy as np
from PIL import Image

from config import EXTRACTED_DIR, IMAGES_DIR, REVIEWED_JSON_PATH, CHAPTER_KEYWORDS
from pipeline.auto_pipeline import (
    parse_answer_pdf, CIRCLE_MAP, SCORE_RE,
    _classify_chapter, _classify_qtype,
)

QSTART_RE  = re.compile(r'^(\d{1,2})\.\s*(.+)$')
CIRCLE_RE  = re.compile(r'^([①②③④⑤])\s*(.*)$')

COL_MARGIN  = 14    # 컬럼 크롭 좌우 여유 (pt)
MIN_DESC_H  = 36    # 설명 이미지로 인정할 최소 높이 (pt)
CROP_DPI    = 200


# ──────────────────────────────────────────────
# 텍스트 레이어 감지
# ──────────────────────────────────────────────

def has_text_layer(pdf_path: Path, sample_pages: int = 5) -> bool:
    doc = fitz.open(str(pdf_path))
    n = min(sample_pages, len(doc))
    total = sum(len(doc[i].get_text().strip()) for i in range(n))
    doc.close()
    return total > 400


# ──────────────────────────────────────────────
# 페이지 → 라인/이미지 블록
# ──────────────────────────────────────────────

def _page_lines_images(page: fitz.Page) -> tuple[list[dict], list[tuple]]:
    d = page.get_text("dict")
    lines, imgs = [], []
    for blk in d["blocks"]:
        if blk["type"] != 0:
            bb = blk["bbox"]
            if (bb[2] - bb[0]) > 6 and (bb[3] - bb[1]) > 6:
                imgs.append(tuple(bb))
            continue
        for line in blk["lines"]:
            txt = "".join(s["text"] for s in line["spans"]).strip()
            if not txt:
                continue
            bb = line["bbox"]
            lines.append({"x0": bb[0], "y0": bb[1], "x1": bb[2], "y1": bb[3], "text": txt})
    return lines, imgs


# ──────────────────────────────────────────────
# 문항 추출
# ──────────────────────────────────────────────

def extract_from_text_pdf(
    q_pdf: Path,
    answers: dict[int, int],
    source_file: str,
) -> tuple[list[dict], list[dict]]:
    """반환: (questions, crop_specs)
    crop_specs: [{"q_number","page_idx","rect_pt":(x0,y0,x1,y1)}, ...]  (좌표 단위 pt)
    """
    questions:  list[dict] = []
    crop_specs: list[dict] = []

    doc = fitz.open(str(q_pdf))
    for pno, page in enumerate(doc):
        pw, ph = page.rect.width, page.rect.height
        mid = pw / 2
        lines, imgs = _page_lines_images(page)

        cols = [
            ([l for l in lines if (l["x0"] + l["x1"]) / 2 < mid],
             [b for b in imgs if (b[0] + b[2]) / 2 < mid], 0.0, mid + COL_MARGIN),
            ([l for l in lines if (l["x0"] + l["x1"]) / 2 >= mid],
             [b for b in imgs if (b[0] + b[2]) / 2 >= mid], mid - COL_MARGIN, pw),
        ]

        for col_lines, col_imgs, cx0, cx1 in cols:
            col_lines.sort(key=lambda l: (l["y0"], l["x0"]))

            # 문항 시작 라인
            starts = []
            for l in col_lines:
                m = QSTART_RE.match(l["text"])
                if m and 1 <= int(m.group(1)) <= 50 and l["x0"] < cx0 + 70:
                    starts.append((int(m.group(1)), m.group(2), l))

            for si, (q_no, stem, start_line) in enumerate(starts):
                y_top  = start_line["y0"]
                y_next = starts[si + 1][2]["y0"] if si + 1 < len(starts) else ph

                qlines = [l for l in col_lines if y_top - 2 <= l["y0"] < y_next - 2]
                qimgs  = [b for b in col_imgs if y_top - 2 <= b[1] < y_next - 2]

                # 보기 라인
                choice_lines = []
                for l in qlines:
                    cm = CIRCLE_RE.match(l["text"])
                    if cm:
                        choice_lines.append((CIRCLE_MAP[cm.group(1)], cm.group(2).strip(), l))

                # seq별 첫 보기만 (중복/이어진 줄 방지)
                seen_seq = {}
                for seq, content, l in choice_lines:
                    if seq not in seen_seq:
                        seen_seq[seq] = (content, l)

                question_text = SCORE_RE.sub("", stem).strip()
                # 분류용 전체 텍스트(보기 제외)
                classify_text = " ".join(
                    l["text"] for l in qlines
                    if not CIRCLE_RE.match(l["text"])
                )

                ans = answers.get(q_no, 0)
                q = {
                    "source_file":       source_file,
                    "q_number":          q_no,
                    "content":           question_text,
                    "image_paths":       [],
                    "choices":           [],
                    "answer_seq":        ans,
                    "correct_choice_id": f"c_{q_no:03d}_{ans}" if ans else "",
                    "chapter":           None,
                    "topic":             None,
                    "q_type":            _classify_qtype(classify_text),
                    "difficulty":        3,
                    "is_verified":       1,
                    "explanation":       None,
                }
                _classify_chapter(q, classify_text)

                stem_bottom   = start_line["y1"]
                region_bottom = max([l["y1"] for l in qlines] +
                                    [b[3] for b in qimgs] + [stem_bottom])
                region_bottom = min(region_bottom, y_next - 2)

                if len(seen_seq) >= 4:
                    # ── 텍스트 보기 ──
                    for seq in sorted(seen_seq):
                        q["choices"].append({
                            "choice_id":  f"c_{q_no:03d}_{seq}",
                            "content":    seen_seq[seq][0] or f"보기 {seq}",
                            "image_path": None,
                        })
                    choices_top = min(l["y0"] for _, l in seen_seq.values())
                    # 설명 이미지 = 질문과 보기 사이 (자료/그림이 있을 때만)
                    mid_lines = [l for l in qlines
                                 if l["y0"] >= stem_bottom - 1 and l["y1"] <= choices_top - 1
                                 and not CIRCLE_RE.match(l["text"])]
                    mid_imgs  = [b for b in qimgs if b[1] >= stem_bottom - 1 and b[3] <= choices_top - 1]
                    if (mid_lines or mid_imgs):
                        d_top = stem_bottom + 2
                        d_bot = choices_top - 2
                        if d_bot - d_top >= MIN_DESC_H:
                            crop_specs.append({
                                "q_number": q_no, "page_idx": pno,
                                "rect_pt": (cx0, d_top, cx1, d_bot),
                            })
                else:
                    # ── 사진 보기 폴백: 설명+보기 전체를 이미지로 ──
                    for s in range(1, 5):
                        q["choices"].append({
                            "choice_id":  f"c_{q_no:03d}_{s}",
                            "content":    f"① ② ③ ④ 중 {s}번",
                            "image_path": None,
                        })
                    d_top = stem_bottom + 2
                    if region_bottom - d_top >= MIN_DESC_H:
                        crop_specs.append({
                            "q_number": q_no, "page_idx": pno,
                            "rect_pt": (cx0, d_top, cx1, region_bottom),
                        })

                questions.append(q)

    doc.close()

    # 중복 q_number 제거
    seen = set()
    uq = []
    for q in questions:
        if q["q_number"] in seen:
            continue
        seen.add(q["q_number"])
        uq.append(q)
    uq.sort(key=lambda q: q["q_number"])

    seen_r = set()
    ur = []
    for r in crop_specs:
        if r["q_number"] in seen_r:
            continue
        seen_r.add(r["q_number"])
        ur.append(r)
    return uq, ur


# ──────────────────────────────────────────────
# 이미지 크롭 (pt → px)
# ──────────────────────────────────────────────

def crop_images_pt(q_pdf: Path, crop_specs: list[dict], dpi: int = CROP_DPI) -> dict[int, str]:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    stem = q_pdf.stem
    doc  = fitz.open(str(q_pdf))
    scale = dpi / 72
    mat   = fitz.Matrix(scale, scale)
    page_imgs: dict[int, Image.Image] = {}

    result: dict[int, str] = {}
    for spec in crop_specs:
        pno = spec["page_idx"]
        if pno not in page_imgs:
            pix = doc[pno].get_pixmap(matrix=mat)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                arr = arr[:, :, :3]
            page_imgs[pno] = Image.fromarray(arr)

        img = page_imgs[pno]
        rx0, ry0, rx1, ry1 = spec["rect_pt"]
        padx, pady = 4, 4
        x0 = max(0, int(rx0 * scale) - padx)
        x1 = min(img.width,  int(rx1 * scale) + padx)
        y0 = max(0, int(ry0 * scale) - pady)
        y1 = min(img.height, int(ry1 * scale) + pady)
        if x1 - x0 < 10 or y1 - y0 < 10:
            continue
        img.crop((x0, y0, x1, y1)).save(str(IMAGES_DIR / f"{stem}_q{spec['q_number']:03d}.png"))
        result[spec["q_number"]] = str(IMAGES_DIR / f"{stem}_q{spec['q_number']:03d}.png")

    doc.close()
    return result


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def run_text_pipeline(q_pdf: Path, a_pdf: Path, progress_cb=None) -> tuple[int, int]:
    def log(ratio, msg):
        try:
            print(f"[{int(ratio*100):3d}%] {msg}", flush=True)
        except (ValueError, OSError):
            pass
        if progress_cb:
            progress_cb(ratio, msg)

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    log(0.05, f"답지 파싱: {a_pdf.name}")
    answers = parse_answer_pdf(a_pdf)
    log(0.15, f"정답 {len(answers)}개")

    log(0.25, "텍스트 레이어에서 문항 추출 중...")
    questions, crop_specs = extract_from_text_pdf(q_pdf, answers, q_pdf.name)
    log(0.55, f"문항 {len(questions)}개 추출")

    log(0.60, "자료/그림 이미지 크롭 중...")
    cropped = crop_images_pt(q_pdf, crop_specs)
    for q in questions:
        p = cropped.get(q["q_number"])
        if p:
            q["image_paths"] = [p]
    log(0.85, f"크롭 {len(cropped)}개")

    REVIEWED_JSON_PATH.write_text(
        json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
    log(0.90, "JSON 저장")

    from app.db import init_db, upsert_question
    init_db()
    ok = 0
    for q in questions:
        try:
            upsert_question(q)
            ok += 1
        except Exception as e:
            print(f"  [SKIP] Q{q['q_number']}: {e}")

    has_ans   = sum(1 for q in questions if q["correct_choice_id"])
    text_mode = sum(1 for q in questions
                    if q["choices"] and not q["choices"][0]["content"].startswith("① ② ③ ④ 중"))
    log(1.0, f"완료! {ok}개 적재 · 정답 {has_ans} · 텍스트보기 {text_mode} · 사진보기 {ok-text_mode}")
    return ok, has_ans


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True)
    ap.add_argument("--answers",   required=True)
    args = ap.parse_args()
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    run_text_pipeline(Path(args.questions), Path(args.answers))
