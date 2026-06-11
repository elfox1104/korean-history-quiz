"""
스캔 이미지 PDF → Claude Vision API로 문항 추출.

각 페이지를 PNG로 변환한 뒤 Claude에게 문항 JSON을 직접 뽑아달라고 요청한다.
답지 PDF가 있으면 같은 방식으로 정답을 추출한다.

사용:
    python -m pipeline.vision_extractor --questions data/raw/q.pdf [--answers data/raw/a.pdf]

환경변수:
    ANTHROPIC_API_KEY  (필수)
"""
import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    print("[ERROR] pip install pymupdf")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("[ERROR] pip install anthropic")
    sys.exit(1)

from config import EXTRACTED_DIR, IMAGES_DIR, REVIEWED_JSON_PATH

# ──────────────────────────────────────────────
# PDF 페이지 → PNG bytes
# ──────────────────────────────────────────────

def pdf_pages_to_images(pdf_path: Path, dpi: int = 150) -> list[bytes]:
    """각 페이지를 PNG bytes 리스트로 반환한다."""
    doc = fitz.open(str(pdf_path))
    images = []
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    for page in doc:
        pix = page.get_pixmap(matrix=mat)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


# ──────────────────────────────────────────────
# 문제지 페이지 → 문항 추출
# ──────────────────────────────────────────────

QUESTION_PROMPT = """이 이미지는 한국사능력검정시험 문제지 페이지입니다.

이 페이지에 있는 모든 문항을 아래 JSON 형식으로 추출해 주세요.
문항이 없는 페이지(표지, 안내 페이지 등)이면 빈 배열 []을 반환하세요.

반환 형식 (JSON 배열):
[
  {
    "q_number": 1,
    "content": "문제 본문 전체 (사료, 지문 포함)",
    "choices": [
      {"seq": 1, "content": "보기1 내용"},
      {"seq": 2, "content": "보기2 내용"},
      {"seq": 3, "content": "보기3 내용"},
      {"seq": 4, "content": "보기4 내용"},
      {"seq": 5, "content": "보기5 내용"}
    ],
    "has_image": true
  }
]

주의사항:
- 보기 번호는 ①②③④⑤ 또는 1~5를 seq 숫자로 변환하세요.
- 사료·지문·조건 등 문제 본문에 포함된 텍스트는 content에 모두 담으세요.
- 지도·사진·도표가 있는 문항은 has_image를 true로 설정하세요.
- JSON만 반환하고 다른 설명은 쓰지 마세요.
"""

ANSWER_PROMPT = """이 이미지는 한국사능력검정시험 정답표입니다.

모든 문항의 정답을 아래 JSON 형식으로 추출해 주세요.
정답표가 없는 페이지이면 빈 객체 {}를 반환하세요.

반환 형식:
{"1": 3, "2": 1, "3": 4, ...}
(키: 문항번호 문자열, 값: 정답 번호 1~5 정수)

JSON만 반환하고 다른 설명은 쓰지 마세요.
"""


def _call_vision(client: anthropic.Anthropic, img_bytes: bytes, prompt: str, retries: int = 3) -> str:
    img_b64 = base64.standard_b64encode(img_bytes).decode()
    for attempt in range(retries):
        try:
            msg = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                        {"type": "text",  "text": prompt},
                    ],
                }],
            )
            return msg.content[0].text.strip()
        except anthropic.RateLimitError:
            wait = 20 * (attempt + 1)
            print(f"    Rate limit — {wait}초 대기...")
            time.sleep(wait)
        except Exception as e:
            print(f"    API 오류: {e}")
            if attempt == retries - 1:
                raise
            time.sleep(5)
    return "[]"


def _extract_json(text: str, fallback):
    """응답 텍스트에서 JSON 부분만 파싱한다."""
    # 코드블록 제거
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # JSON 배열/객체 부분만 추출 시도
        m = re.search(r'(\[.*\]|\{.*\})', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return fallback


# ──────────────────────────────────────────────
# 메인 파이프라인
# ──────────────────────────────────────────────

def run_vision_extraction(
    questions_pdf: Path,
    answers_pdf: Optional[Path] = None,
    api_key: Optional[str] = None,
) -> Path:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("[ERROR] ANTHROPIC_API_KEY 환경변수를 설정하거나 --api-key 옵션을 사용하세요.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=key)

    # ── 1. 문제지 추출 ──
    print(f"[1/3] 문제지 PDF 이미지 변환: {questions_pdf.name}")
    q_images = pdf_pages_to_images(questions_pdf)
    print(f"      {len(q_images)}페이지")

    all_questions: list[dict] = []
    source_file = questions_pdf.name

    for i, img in enumerate(q_images):
        print(f"  페이지 {i+1}/{len(q_images)} 처리 중...", end=" ", flush=True)
        raw_text = _call_vision(client, img, QUESTION_PROMPT)
        page_qs  = _extract_json(raw_text, [])
        if page_qs:
            all_questions.extend(page_qs)
            print(f"{len(page_qs)}개 문항 추출")
        else:
            print("문항 없음")
        time.sleep(0.5)  # API 부하 방지

    print(f"\n  총 {len(all_questions)}개 문항 추출 완료")

    # ── 2. 답지 추출 ──
    answers_map: dict[int, int] = {}
    if answers_pdf and answers_pdf.exists():
        print(f"\n[2/3] 답지 PDF 처리: {answers_pdf.name}")
        a_images = pdf_pages_to_images(answers_pdf)
        for i, img in enumerate(a_images):
            print(f"  답지 페이지 {i+1}/{len(a_images)} 처리 중...", end=" ", flush=True)
            raw_text = _call_vision(client, img, ANSWER_PROMPT)
            page_ans = _extract_json(raw_text, {})
            if page_ans:
                for k, v in page_ans.items():
                    try:
                        answers_map[int(k)] = int(v)
                    except (ValueError, TypeError):
                        pass
                print(f"{len(page_ans)}개 정답")
            else:
                print("정답 없음")
            time.sleep(0.5)
        print(f"  총 {len(answers_map)}개 정답 수집")
    else:
        print("\n[2/3] 답지 없음 — 정답을 별도로 입력해야 합니다.")

    # ── 3. 구조화 및 저장 ──
    print("\n[3/3] 문항 구조화 및 저장...")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

    structured: list[dict] = []
    for q in all_questions:
        q_no    = int(q.get("q_number", 0))
        if q_no == 0:
            continue
        content = q.get("content", "").strip()
        choices_raw = q.get("choices", [])

        # choice_id 생성
        choices = []
        for c in choices_raw:
            seq = int(c.get("seq", 0))
            if seq == 0:
                continue
            choices.append({
                "choice_id":  f"c_{q_no:03d}_{seq}",
                "content":    c.get("content", "").strip(),
                "image_path": None,
            })

        ans_seq = answers_map.get(q_no, 0)
        correct_id = f"c_{q_no:03d}_{ans_seq}" if ans_seq else ""

        structured.append({
            "source_file":       source_file,
            "q_number":          q_no,
            "content":           content,
            "image_paths":       [],          # 이미지 귀속은 추후 수동 추가
            "choices":           choices,
            "answer_seq":        ans_seq,
            "correct_choice_id": correct_id,
            "chapter":           None,
            "topic":             None,
            "q_type":            "이미지PDF",
            "difficulty":        3,
            "is_verified":       0,           # 반드시 검수 후 1로 변경
            "explanation":       None,
        })

    # 챕터 자동 분류 시도
    try:
        from pipeline.classifier import classify_by_keywords
        structured = [classify_by_keywords(q) for q in structured]
        print(f"  챕터 자동 분류 완료")
    except Exception as e:
        print(f"  챕터 분류 스킵: {e}")

    REVIEWED_JSON_PATH.write_text(
        json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    no_answer  = [q for q in structured if not q["correct_choice_id"]]
    no_choices = [q for q in structured if len(q["choices"]) < 2]
    print(f"\n  저장 완료: {REVIEWED_JSON_PATH}")
    print(f"  전체 문항  : {len(structured)}개")
    print(f"  정답 없음  : {len(no_answer)}개  → 검수 필요")
    print(f"  보기 부족  : {len(no_choices)}개  → 검수 필요")
    print(f"  is_verified=0 → 관리자 페이지에서 '전체 승인' 후 DB 적재하세요.")

    return REVIEWED_JSON_PATH


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vision OCR 추출기")
    parser.add_argument("--questions", required=True)
    parser.add_argument("--answers",   default=None)
    parser.add_argument("--api-key",   default=None)
    args = parser.parse_args()

    run_vision_extraction(
        Path(args.questions),
        Path(args.answers) if args.answers else None,
        api_key=args.api_key,
    )
