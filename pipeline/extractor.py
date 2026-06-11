"""
PDF에서 페이지별 텍스트와 이미지를 추출한다.

사용:
    python -m pipeline.extractor --questions data/raw/q.pdf --answers data/raw/a.pdf
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    print("[ERROR] PyMuPDF가 설치되지 않았습니다. pip install pymupdf")
    sys.exit(1)

from config import EXTRACTED_DIR, IMAGES_DIR, RAW_JSON_PATH

# ──────────────────────────────────────────────
# 이미지 추출
# ──────────────────────────────────────────────

def extract_images_from_pdf(pdf_path: Path) -> dict[int, list[dict]]:
    """
    페이지별로 이미지를 추출하고 로컬에 저장한다.
    반환: { page_index: [{"path": str, "bbox": (x0,y0,x1,y1)}, ...] }
    """
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    stem = pdf_path.stem
    result: dict[int, list[dict]] = {}

    for page_idx, page in enumerate(doc):
        result[page_idx] = []
        image_list = page.get_images(full=True)

        for img_seq, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                img_bytes  = base_image["image"]
                img_ext    = base_image["ext"]
            except Exception:
                continue

            fname = f"{stem}_p{page_idx:03d}_i{img_seq:02d}.{img_ext}"
            fpath = IMAGES_DIR / fname
            fpath.write_bytes(img_bytes)

            # 이미지가 페이지 어느 위치에 있는지 bbox 확보
            bbox = _get_image_bbox(page, xref)
            result[page_idx].append({"path": str(fpath), "bbox": bbox})

    doc.close()
    return result


def _get_image_bbox(page: fitz.Page, xref: int) -> tuple:
    """이미지 xref의 페이지 내 bounding box를 반환한다."""
    for item in page.get_image_info(xrefs=True):
        if item.get("xref") == xref:
            r = item["bbox"]
            return (r[0], r[1], r[2], r[3])
    return (0, 0, 0, 0)


# ──────────────────────────────────────────────
# 텍스트 추출
# ──────────────────────────────────────────────

def extract_text_blocks(pdf_path: Path) -> list[dict]:
    """
    페이지별로 텍스트 블록을 추출한다.
    반환: [{"page": int, "y0": float, "y1": float, "text": str}, ...]
    """
    doc = fitz.open(str(pdf_path))
    blocks: list[dict] = []

    for page_idx, page in enumerate(doc):
        raw_blocks = page.get_text("blocks")  # (x0,y0,x1,y1,text,block_no,block_type)
        for b in raw_blocks:
            if b[6] != 0:  # block_type 0 = 텍스트
                continue
            text = b[4].strip()
            if not text:
                continue
            blocks.append({
                "page": page_idx,
                "x0": b[0], "y0": b[1],
                "x1": b[2], "y1": b[3],
                "text": text,
            })

    doc.close()
    return blocks


# ──────────────────────────────────────────────
# 답지 파싱
# ──────────────────────────────────────────────

# 예: "1 - ③", "2. ④", "3-2", "01③" 등 다양한 형식 대응
ANSWER_PATTERNS = [
    re.compile(r'(\d{1,2})\s*[-\.]\s*([①②③④⑤])'),   # "1 - ③"
    re.compile(r'(\d{1,2})\s*[-\.]\s*([1-5])'),         # "1 - 3"
    re.compile(r'(\d{1,2})\s*([①②③④⑤])'),             # "1③"
]
CIRCLE_MAP = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}


def parse_answers(pdf_path: Path) -> dict[int, int]:
    """
    답지 PDF에서 {문항번호: 정답순서(1~5)} 딕셔너리를 반환한다.
    """
    doc = fitz.open(str(pdf_path))
    answers: dict[int, int] = {}

    for page in doc:
        text = page.get_text()
        for pat in ANSWER_PATTERNS:
            for m in pat.finditer(text):
                q_no   = int(m.group(1))
                ans_ch = m.group(2)
                ans_no = CIRCLE_MAP.get(ans_ch, None) or (int(ans_ch) if ans_ch.isdigit() else None)
                if ans_no and q_no not in answers:
                    answers[q_no] = ans_no

    doc.close()
    return answers


# ──────────────────────────────────────────────
# 메인: PDF → raw JSON
# ──────────────────────────────────────────────

def run_extraction(questions_pdf: Path, answers_pdf: Optional[Path] = None) -> Path:
    """
    문제지 PDF를 처리해 questions_raw.json을 생성한다.
    answers_pdf가 있으면 정답을 함께 기록한다.
    """
    print(f"[1/4] 텍스트 블록 추출 중: {questions_pdf.name}")
    text_blocks = extract_text_blocks(questions_pdf)

    print(f"[2/4] 이미지 추출 중...")
    page_images = extract_images_from_pdf(questions_pdf)

    print(f"[3/4] 답지 파싱 중...")
    answers: dict[int, int] = {}
    if answers_pdf and answers_pdf.exists():
        answers = parse_answers(answers_pdf)
        print(f"      정답 {len(answers)}개 파싱 완료")
    else:
        print("      답지 없음 — answer_seq 를 0으로 설정합니다")

    print(f"[4/4] raw JSON 저장 중...")
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

    # 텍스트 블록을 그대로 raw JSON에 저장 (parser.py가 구조화함)
    raw_data = {
        "source_file": questions_pdf.name,
        "text_blocks": text_blocks,
        "page_images": {str(k): v for k, v in page_images.items()},
        "answers": {str(k): v for k, v in answers.items()},
    }
    RAW_JSON_PATH.write_text(
        json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"      저장 완료: {RAW_JSON_PATH}")
    print(f"      텍스트 블록 {len(text_blocks)}개, "
          f"이미지 {sum(len(v) for v in page_images.values())}개")
    return RAW_JSON_PATH




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDF 추출기")
    parser.add_argument("--questions", required=True, help="문제지 PDF 경로")
    parser.add_argument("--answers",   default=None,  help="답지 PDF 경로 (선택)")
    args = parser.parse_args()

    q_path = Path(args.questions)
    a_path = Path(args.answers) if args.answers else None

    if not q_path.exists():
        print(f"[ERROR] 파일을 찾을 수 없습니다: {q_path}")
        sys.exit(1)

    run_extraction(q_path, a_path)
