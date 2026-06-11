"""
extractor.py가 만든 questions_raw.json을 문항 구조로 파싱한다.

출력: data/extracted/questions_raw_parsed.json
      (관리자 검수 후 questions_reviewed.json으로 복사)

사용:
    python -m pipeline.parser
"""
import json
import re
import sys
from pathlib import Path
from typing import Optional

from config import EXTRACTED_DIR, RAW_JSON_PATH, IMAGES_DIR

# ──────────────────────────────────────────────
# 정규식
# ──────────────────────────────────────────────

# 문항 번호 줄 감지: "1.", "01.", "1 ." 등으로 시작하는 줄
Q_START = re.compile(r'^(\d{1,2})[.\s]\s*(.*)$')

# 보기 원문자 ①~⑤
CHOICE_CIRCLE = re.compile(r'^([①②③④⑤])\s*(.+)$')

# 보기 숫자 형식 "1) ...", "① ..." (원문자 재사용), "ㄱ. ..."
CHOICE_DIGIT  = re.compile(r'^([1-5])[)\.]\s*(.+)$')

CIRCLE_TO_SEQ = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}

# ──────────────────────────────────────────────
# 보기 파싱 헬퍼
# ──────────────────────────────────────────────

def _parse_choice_line(line: str) -> Optional[tuple[int, str]]:
    """보기 줄이면 (seq 1~5, 내용)을 반환, 아니면 None."""
    m = CHOICE_CIRCLE.match(line)
    if m:
        return CIRCLE_TO_SEQ[m.group(1)], m.group(2).strip()
    m = CHOICE_DIGIT.match(line)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None


# ──────────────────────────────────────────────
# 이미지 귀속 헬퍼
# ──────────────────────────────────────────────

def _assign_images_to_questions(
    questions: list[dict],
    page_images: dict[str, list[dict]],
    text_blocks: list[dict],
) -> None:
    """
    이미지 bbox Y좌표와 문항 텍스트 Y좌표를 비교해
    각 문항의 image_paths에 이미지 경로를 할당한다.
    판단 불가 이미지는 q_number=0(미할당)으로 표시한다.
    """
    # 문항별 페이지·Y범위 구축
    q_ranges: list[dict] = []
    for i, q in enumerate(questions):
        q_ranges.append({
            "idx":    i,
            "page":   q.get("_page", 0),
            "y_start": q.get("_y_start", 0),
            "y_end":   q.get("_y_end", 9999),
        })

    for page_str, imgs in page_images.items():
        page_no = int(page_str)
        for img in imgs:
            bbox = img["bbox"]
            img_y_center = (bbox[1] + bbox[3]) / 2
            assigned = False
            for r in q_ranges:
                if r["page"] == page_no and r["y_start"] <= img_y_center <= r["y_end"]:
                    questions[r["idx"]]["image_paths"].append(img["path"])
                    assigned = True
                    break
            if not assigned:
                # 같은 페이지의 가장 가까운 문항에 귀속
                same_page = [r for r in q_ranges if r["page"] == page_no]
                if same_page:
                    closest = min(same_page, key=lambda r: abs((r["y_start"]+r["y_end"])/2 - img_y_center))
                    questions[closest["idx"]]["image_paths"].append(img["path"])
                    questions[closest["idx"]]["_image_unverified"] = True


# ──────────────────────────────────────────────
# 메인 파서
# ──────────────────────────────────────────────

def parse_raw_json(raw_path: Path = RAW_JSON_PATH) -> list[dict]:
    """
    questions_raw.json → 문항 구조화 리스트 반환.
    """
    if not raw_path.exists():
        print(f"[ERROR] raw JSON 없음: {raw_path}")
        sys.exit(1)

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    source_file  = raw.get("source_file", "unknown.pdf")
    text_blocks  = raw.get("text_blocks", [])
    page_images  = raw.get("page_images", {})
    answers_map  = {int(k): v for k, v in raw.get("answers", {}).items()}

    questions: list[dict] = []
    current_q: Optional[dict] = None

    for block in text_blocks:
        lines = block["text"].splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 문항 번호 감지
            m = Q_START.match(line)
            if m and 1 <= int(m.group(1)) <= 99:
                q_no = int(m.group(1))
                # 이전 문항 확정
                if current_q:
                    _finalize_question(current_q, answers_map, source_file)
                    questions.append(current_q)

                current_q = {
                    "source_file":  source_file,
                    "q_number":     q_no,
                    "content":      m.group(2).strip(),
                    "image_paths":  [],
                    "choices":      [],          # [{"seq":int, "content":str}]
                    "answer_seq":   answers_map.get(q_no, 0),
                    "correct_choice_id": "",
                    "chapter":      None,
                    "topic":        None,
                    "q_type":       None,
                    "difficulty":   3,
                    "is_verified":  0,
                    "explanation":  None,
                    # 내부 위치 정보 (이미지 귀속용, 최종 JSON에서 제거)
                    "_page":        block["page"],
                    "_y_start":     block["y0"],
                    "_y_end":       block["y1"],
                    "_image_unverified": False,
                }
                continue

            if current_q is None:
                continue

            # 보기 감지
            choice = _parse_choice_line(line)
            if choice:
                seq, text = choice
                # choice_id: "c_{q_number:03d}_{seq}"
                cid = f"c_{current_q['q_number']:03d}_{seq}"
                current_q["choices"].append({
                    "choice_id":  cid,
                    "content":    text,
                    "image_path": None,
                })
                # Y 범위 확장
                current_q["_y_end"] = block["y1"]
            else:
                # 문항 본문 이어붙이기
                current_q["content"] += " " + line
                current_q["_y_end"] = block["y1"]

    # 마지막 문항 처리
    if current_q:
        _finalize_question(current_q, answers_map, source_file)
        questions.append(current_q)

    # 이미지 귀속
    _assign_images_to_questions(questions, page_images, text_blocks)

    # 내부 위치 필드 제거
    for q in questions:
        for key in ["_page", "_y_start", "_y_end"]:
            q.pop(key, None)

    return questions


def _finalize_question(q: dict, answers_map: dict, source_file: str) -> None:
    """answer_seq → correct_choice_id 변환."""
    seq = q.get("answer_seq", 0)
    if seq and 1 <= seq <= 5:
        q["correct_choice_id"] = f"c_{q['q_number']:03d}_{seq}"
    else:
        q["correct_choice_id"] = ""  # 검수 필요


def save_parsed_json(questions: list[dict]) -> Path:
    out_path = EXTRACTED_DIR / "questions_raw_parsed.json"
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[parser] {len(questions)}개 문항 파싱 완료 → {out_path}")
    return out_path


if __name__ == "__main__":
    questions = parse_raw_json()
    save_parsed_json(questions)

    # 간단 통계 출력
    no_answer  = [q for q in questions if not q["correct_choice_id"]]
    no_choices = [q for q in questions if len(q["choices"]) < 2]
    has_image  = [q for q in questions if q["image_paths"]]
    unverified_img = [q for q in questions if q.get("_image_unverified")]

    print(f"  정답 없음:    {len(no_answer)}개  → 수동 검수 필요")
    print(f"  보기 부족:    {len(no_choices)}개  → 수동 검수 필요")
    print(f"  이미지 포함:  {len(has_image)}개")
    print(f"  이미지 미할당:{len(unverified_img)}개  → 검수 권장")
