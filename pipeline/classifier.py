"""
챕터·주제·문항유형 자동 분류기.

1단계: 키워드 기반 규칙 분류 (config.CHAPTER_KEYWORDS)
2단계: 분류 실패 시 content를 그대로 두고 is_verified=0 유지 (수동 검수)
(선택) --llm 플래그: Claude API로 자동 분류

사용:
    python -m pipeline.classifier                     # 키워드 기반
    python -m pipeline.classifier --llm               # LLM 기반 (API 키 필요)
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from config import CHAPTER_KEYWORDS, EXTRACTED_DIR

PARSED_JSON  = EXTRACTED_DIR / "questions_raw_parsed.json"
REVIEWED_JSON = EXTRACTED_DIR / "questions_reviewed.json"

# 유형 키워드
TYPE_KEYWORDS: dict[str, list[str]] = {
    "사료분석": ["다음 자료", "다음 문서", "다음 기록", "밑줄 친", "괄호 안"],
    "지도":    ["지도", "영역", "위치"],
    "연표":    ["연표", "순서", "시기순", "앞뒤"],
    "인물":    ["인물", "다음 인물", "업적", "활동"],
    "문화재":  ["유물", "문화재", "건축물", "탑", "불상"],
    "도표":    ["표", "그래프", "통계"],
}


# ──────────────────────────────────────────────
# 키워드 분류
# ──────────────────────────────────────────────

def classify_by_keywords(q: dict) -> dict:
    text = q.get("content", "") + " ".join(
        c["content"] for c in q.get("choices", [])
    )

    # 챕터
    if not q.get("chapter"):
        for chapter, kws in CHAPTER_KEYWORDS.items():
            if any(kw in text for kw in kws):
                q["chapter"] = chapter
                break

    # 주제: 챕터 내 첫 번째 매칭 키워드
    if not q.get("topic") and q.get("chapter"):
        kws = CHAPTER_KEYWORDS.get(q["chapter"], [])
        for kw in kws:
            if kw in text:
                q["topic"] = kw
                break

    # 유형
    if not q.get("q_type"):
        for qtype, kws in TYPE_KEYWORDS.items():
            if any(kw in text for kw in kws):
                q["q_type"] = qtype
                break
        if not q.get("q_type"):
            q["q_type"] = "일반"

    return q


# ──────────────────────────────────────────────
# LLM 분류 (선택, Claude API)
# ──────────────────────────────────────────────

def classify_by_llm(questions: list[dict]) -> list[dict]:
    """
    Claude API로 챕터/주제/유형을 분류한다.
    ANTHROPIC_API_KEY 환경 변수가 필요하다.
    """
    try:
        import anthropic
    except ImportError:
        print("[LLM] anthropic 패키지 없음. pip install anthropic")
        return questions

    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[LLM] ANTHROPIC_API_KEY 환경변수가 없습니다.")
        return questions

    client = anthropic.Anthropic(api_key=api_key)
    chapters = list(CHAPTER_KEYWORDS.keys())

    # 분류가 안 된 문항만 LLM 처리
    targets = [q for q in questions if not q.get("chapter")]
    print(f"[LLM] {len(targets)}개 문항 분류 중...")

    for i, q in enumerate(targets):
        prompt = f"""다음 한국사 시험 문항을 분류해줘.

문항: {q['content'][:300]}

아래 챕터 중 하나를 골라줘: {', '.join(chapters)}
주제(핵심 사건·인물·제도 등 3단어 이내):
문항유형(사료분석/지도/연표/인물/문화재/도표/일반 중 하나):

JSON으로만 답해줘:
{{"chapter": "...", "topic": "...", "q_type": "..."}}"""

        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            # JSON 블록 추출
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                result = json.loads(m.group())
                q["chapter"] = result.get("chapter") or q.get("chapter")
                q["topic"]   = result.get("topic")   or q.get("topic")
                q["q_type"]  = result.get("q_type")  or q.get("q_type")
        except Exception as e:
            print(f"  [LLM] 문항 {q['q_number']} 분류 실패: {e}")

        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(targets)} 완료")

    return questions


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def run_classification(use_llm: bool = False) -> Path:
    if not PARSED_JSON.exists():
        print(f"[ERROR] 파싱 JSON 없음: {PARSED_JSON}")
        print("먼저 pipeline.parser 를 실행하세요.")
        sys.exit(1)

    questions: list[dict] = json.loads(PARSED_JSON.read_text(encoding="utf-8"))
    print(f"[classifier] {len(questions)}개 문항 분류 시작")

    # 1단계: 키워드 기반
    questions = [classify_by_keywords(q) for q in questions]

    # 2단계: LLM (선택)
    if use_llm:
        questions = classify_by_llm(questions)

    # 분류 통계
    no_chapter = [q for q in questions if not q.get("chapter")]
    print(f"  챕터 분류 완료: {len(questions)-len(no_chapter)}/{len(questions)}개")
    print(f"  미분류: {len(no_chapter)}개 (수동 검수 필요)")

    # 저장 (관리자가 이 파일을 검수 후 questions_reviewed.json으로 복사)
    REVIEWED_JSON.write_text(
        json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[classifier] 저장 완료: {REVIEWED_JSON}")
    print("  검수 후 is_verified 값을 1로 바꾸면 학습에 사용됩니다.")
    return REVIEWED_JSON


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="Claude API 분류 사용")
    args = parser.parse_args()
    run_classification(use_llm=args.llm)
