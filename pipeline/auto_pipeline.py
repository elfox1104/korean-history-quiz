"""
완전 자동 파이프라인: 문제지 PDF + 답지 PDF → SQLite DB 적재

핵심: 한국사 시험지는 2단(좌/우 컬럼) 편집이므로, 각 문항을
자기 컬럼 영역만 크롭해야 옆 문항과 섞이지 않는다.

1. 답지 PDF → 텍스트 추출 → 정답 파싱 (①②③④ 기준)
2. 문제지 PDF → 페이지별 OCR → 컬럼 분리 → 문항별 영역 추적
3. 문항별 컬럼-스코프 이미지 크롭
4. 정답 결합 + 챕터 분류 → DB 적재
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

CIRCLE_MAP = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}
SCORE_RE   = re.compile(r'\[\d점\]')
# "9. 다음...", "10 다음...", "11. (가)..." — 번호 뒤 . 또는 공백 + 실제 내용
Q_NUM_RE   = re.compile(r'^(\d{1,2})[.\s]\s*(\S.*)$')

COL_MARGIN = 30   # 컬럼 크롭 시 좌우 여유 px


# ──────────────────────────────────────────────
# 1. 답지 파싱
# ──────────────────────────────────────────────

def parse_answer_pdf(pdf_path: Path) -> dict[int, int]:
    doc = fitz.open(str(pdf_path))
    full_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    answers: dict[int, int] = {}
    for m in re.finditer(r'(\d{1,2})\s+([①②③④⑤])\s+\d', full_text):
        q_no = int(m.group(1))
        if 1 <= q_no <= 100:
            answers[q_no] = CIRCLE_MAP[m.group(2)]

    if len(answers) < 10:  # fallback
        for m in re.finditer(r'(\d{1,2})\s+([①②③④⑤])', full_text):
            q_no = int(m.group(1))
            if 1 <= q_no <= 100 and q_no not in answers:
                answers[q_no] = CIRCLE_MAP[m.group(2)]

    return answers


# ──────────────────────────────────────────────
# 2. OCR
# ──────────────────────────────────────────────

def _get_ocr_reader():
    # easyocr이 진행바(█)를 stdout/stderr에 출력하면 Windows cp949 콘솔에서 깨진다.
    # 실제 stdout.buffer를 감싸면 wrapper 정리 시 Streamlit의 버퍼가 닫혀버리므로,
    # 모델 로드 동안에만 메모리 sink로 출력을 흡수한다(실제 버퍼는 건드리지 않음).
    import easyocr
    orig_out, orig_err = sys.stdout, sys.stderr
    sink = io.StringIO()
    sys.stdout = sys.stderr = sink
    try:
        reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    finally:
        sys.stdout, sys.stderr = orig_out, orig_err
    return reader


def ocr_page(reader, page: fitz.Page, dpi: int = 200) -> tuple[list[dict], int, int]:
    """
    한 페이지 OCR.
    반환: (blocks, page_width_px, page_height_px)
    blocks: [{"text", "x0", "y0", "x1", "y1", "conf"}, ...]
    """
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img_np = img_np[:, :, :3]

    results = reader.readtext(img_np, detail=1, paragraph=False)

    blocks = []
    for bbox, text, conf in results:
        if conf < 0.25 or not text.strip():
            continue
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        blocks.append({
            "text": text.strip(),
            "x0": float(min(xs)), "y0": float(min(ys)),
            "x1": float(max(xs)), "y1": float(max(ys)),
            "conf": conf,
        })

    blocks.sort(key=lambda b: (b["y0"], b["x0"]))
    return blocks, pix.width, pix.height


# ──────────────────────────────────────────────
# 3. 컬럼 인식 문항 영역 추적 + 헤더/설명/보기 분리
# ──────────────────────────────────────────────

HEADER_CONT_GAP = 78   # 질문 2번째 줄 병합 허용 세로 간격
MIN_DESC_H      = 40   # 설명+보기 이미지로 인정할 최소 높이 px


def _is_question_start(block: dict, col_left: float) -> Optional[tuple[int, str]]:
    """블록이 '문항 시작'이면 (번호, 본문) 반환."""
    text = block["text"].strip()
    m = Q_NUM_RE.match(text)
    if not m:
        return None
    q_no = int(m.group(1))
    if not (1 <= q_no <= 100):
        return None
    body = m.group(2).strip()
    if len(body) < 2:
        return None
    if block["x0"] > col_left + 260:
        return None
    return q_no, body


def extract_question_regions(
    all_pages: list[tuple[int, list[dict], int, int]],
    answers:    dict[int, int],
    source_file: str,
) -> tuple[list[dict], list[dict]]:
    """
    OCR 결과를 컬럼별로 분리하고 각 문항을 헤더/설명/보기로 나눈다.
    반환: (questions, crop_specs)
    crop_specs: [{"q_number","page_idx","rect":(x0,y0,x1,y1)}, ...]
                설명 이미지가 없는 문항은 목록에 포함되지 않음.
    """
    questions:  list[dict] = []
    crop_specs: list[dict] = []

    for page_idx, blocks, pw, ph in all_pages:
        mid = pw / 2
        columns = [
            ([b for b in blocks if (b["x0"] + b["x1"]) / 2 < mid], 0.0,            mid + COL_MARGIN),
            ([b for b in blocks if (b["x0"] + b["x1"]) / 2 >= mid], mid - COL_MARGIN, float(pw)),
        ]

        for col_blocks, col_x0, col_x1 in columns:
            col_blocks.sort(key=lambda b: b["y0"])

            starts = []
            for b in col_blocks:
                qs = _is_question_start(b, col_x0)
                if qs:
                    starts.append((qs[0], qs[1], b))

            for si, (q_no, body, start_block) in enumerate(starts):
                y_top  = start_block["y0"]
                y_next = starts[si + 1][2]["y0"] if si + 1 < len(starts) else None

                qblocks = [
                    b for b in col_blocks
                    if b["y0"] >= y_top - 5 and (y_next is None or b["y0"] < y_next - 5)
                ]
                if not qblocks:
                    continue
                region_bottom = max(b["y1"] for b in qblocks)
                if y_next is not None:
                    region_bottom = min(region_bottom, y_next - 8)

                # ── 헤더(질문) 텍스트: 시작 블록 + 같은 들여쓰기의 연속 줄 ──
                header_x0     = start_block["x0"]
                header_bottom = start_block["y1"]
                q_text_parts  = [body]
                for b in qblocks:
                    if b is start_block:
                        continue
                    if (b["y0"] < header_bottom + HEADER_CONT_GAP
                            and abs(b["x0"] - header_x0) <= 55
                            and b["y0"] >= header_bottom - 5):
                        q_text_parts.append(b["text"])
                        header_bottom = max(header_bottom, b["y1"])
                question_text = SCORE_RE.sub("", " ".join(q_text_parts)).strip()

                ans = answers.get(q_no, 0)
                q = {
                    "source_file":       source_file,
                    "q_number":          q_no,
                    "content":           question_text,
                    "image_paths":       [],
                    "choices":           [{
                        "choice_id":  f"c_{q_no:03d}_{s}",
                        "content":    f"① ② ③ ④ 중 {s}번",
                        "image_path": None,
                    } for s in range(1, 5)],
                    "answer_seq":        ans,
                    "correct_choice_id": f"c_{q_no:03d}_{ans}" if ans else "",
                    "chapter":           None,
                    "topic":             None,
                    "q_type":            _classify_qtype(question_text),
                    "difficulty":        3,
                    "is_verified":       1,
                    "explanation":       None,
                }
                _classify_chapter(q, question_text)

                # 설명+보기 = 헤더(번호+질문) 아래 전체를 이미지로 크롭
                d_top = header_bottom + 4
                if region_bottom - d_top >= MIN_DESC_H:
                    crop_specs.append({
                        "q_number": q_no, "page_idx": page_idx,
                        "rect": (col_x0, d_top, col_x1, region_bottom),
                    })

                questions.append(q)

    # 중복 q_number 제거 (오인식 방지)
    seen = set()
    uniq_q = []
    for q in questions:
        if q["q_number"] in seen:
            continue
        seen.add(q["q_number"])
        uniq_q.append(q)
    uniq_q.sort(key=lambda q: q["q_number"])

    seen_r = set()
    uniq_r = []
    for r in crop_specs:
        if r["q_number"] in seen_r:
            continue
        seen_r.add(r["q_number"])
        uniq_r.append(r)

    return uniq_q, uniq_r


def _classify_chapter(q: dict, text: str) -> None:
    for chapter, kws in CHAPTER_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                q["chapter"] = chapter
                q["topic"]   = kw
                return


def _classify_qtype(text: str) -> str:
    if any(w in text for w in ["자료", "밑줄", "사료"]):
        return "사료분석"
    if any(w in text for w in ["지도", "영역", "위치"]):
        return "지도"
    if any(w in text for w in ["순서", "연표", "시기"]):
        return "연표"
    return "일반"


# ──────────────────────────────────────────────
# 4. 컬럼-스코프 이미지 크롭
# ──────────────────────────────────────────────

def crop_question_images(
    pdf_path: Path,
    crop_specs: list[dict],   # [{"q_number","page_idx","rect":(x0,y0,x1,y1)}, ...]
    dpi: int = 200,
) -> dict[int, str]:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    doc  = fitz.open(str(pdf_path))
    mat  = fitz.Matrix(dpi / 72, dpi / 72)
    page_imgs: dict[int, Image.Image] = {}

    result: dict[int, str] = {}
    for spec in crop_specs:
        pidx = spec["page_idx"]
        if pidx not in page_imgs:
            pix = doc[pidx].get_pixmap(matrix=mat)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                arr = arr[:, :, :3]
            page_imgs[pidx] = Image.fromarray(arr)

        img = page_imgs[pidx]
        rx0, ry0, rx1, ry1 = spec["rect"]
        padx, pady = 6, 8
        x0 = max(0, int(rx0) - padx)
        x1 = min(img.width,  int(rx1) + padx)
        y0 = max(0, int(ry0) - pady)
        y1 = min(img.height, int(ry1) + pady)
        if x1 - x0 < 10 or y1 - y0 < 10:
            continue
        cropped = img.crop((x0, y0, x1, y1))

        fname = f"{stem}_q{spec['q_number']:03d}.png"
        fpath = IMAGES_DIR / fname
        cropped.save(str(fpath))
        result[spec["q_number"]] = str(fpath)

    doc.close()
    return result


# ──────────────────────────────────────────────
# 5. 메인
# ──────────────────────────────────────────────

def run_auto_pipeline(
    questions_pdf: Path,
    answers_pdf:   Path,
    progress_cb=None,
) -> tuple[int, int]:

    def log(ratio: float, msg: str):
        try:
            print(f"[{int(ratio*100):3d}%] {msg}", flush=True)
        except (ValueError, OSError):
            pass  # stdout이 닫혀 있어도 UI 진행률은 계속 갱신
        if progress_cb:
            progress_cb(ratio, msg)

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 답지
    log(0.05, f"답지 파싱: {answers_pdf.name}")
    answers = parse_answer_pdf(answers_pdf)
    log(0.10, f"정답 {len(answers)}개 파싱 완료")

    # 2. OCR
    log(0.12, "OCR 모델 로드 중...")
    reader = _get_ocr_reader()

    doc = fitz.open(str(questions_pdf))
    total_pages = len(doc)
    all_pages: list[tuple[int, list[dict], int, int]] = []
    for i, page in enumerate(doc):
        log(0.15 + 0.55 * (i / total_pages), f"OCR: {i+1}/{total_pages} 페이지")
        blocks, pw, ph = ocr_page(reader, page, dpi=200)
        all_pages.append((i, blocks, pw, ph))
    doc.close()
    log(0.72, "OCR 완료")

    # 3. 컬럼 인식 문항 추출
    log(0.74, "문항 구조 분석 중...")
    questions, q_ranges = extract_question_regions(all_pages, answers, questions_pdf.name)
    log(0.78, f"문항 {len(questions)}개 추출")

    # 4. 컬럼-스코프 크롭
    log(0.80, "문항별 이미지 크롭 중...")
    cropped_map = crop_question_images(questions_pdf, q_ranges, dpi=200)
    for q in questions:
        path = cropped_map.get(q["q_number"])
        if path:
            q["image_paths"] = [path]
    log(0.90, f"크롭 완료: {len(cropped_map)}개")

    # 5. JSON 저장
    REVIEWED_JSON_PATH.write_text(
        json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(0.93, "JSON 저장 완료")

    # 6. DB 적재
    log(0.95, "DB 적재 중...")
    from app.db import init_db, upsert_question
    init_db()
    ok = 0
    for q in questions:
        try:
            upsert_question(q)
            ok += 1
        except Exception as e:
            print(f"  [SKIP] Q{q['q_number']}: {e}")

    has_answer = sum(1 for q in questions if q["correct_choice_id"])
    log(1.0, f"완료! {ok}개 적재, 정답 {has_answer}개")
    return ok, has_answer


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", required=True)
    parser.add_argument("--answers",   required=True)
    args = parser.parse_args()

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    run_auto_pipeline(Path(args.questions), Path(args.answers))
