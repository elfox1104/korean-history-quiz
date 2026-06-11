"""
출제 · 채점 · 유사문항 추천 로직.
정답은 choice_id 기준으로 판정하므로 보기 순서와 무관하다.
"""
import random
from typing import Optional

import app.db as db
from config import (
    DEFAULT_SESSION_SIZE,
    SCORE_CHAPTER_TOPIC,
    SCORE_CHAPTER_ONLY,
    SCORE_QTYPE,
    SCORE_WRONG_COUNT,
    SCORE_TODAY_PENALTY,
)


# ──────────────────────────────────────────────
# 보기 랜덤화
# ──────────────────────────────────────────────

def get_shuffled_choices(question_id: int) -> list[dict]:
    """
    보기를 랜덤으로 섞어 반환한다.
    choice_id는 유지되므로 어떤 순서로 표시해도 정답 판정이 정확하다.
    """
    rows = db.get_choices(question_id)
    choices = [dict(r) for r in rows]
    random.shuffle(choices)
    return choices


# ──────────────────────────────────────────────
# 채점
# ──────────────────────────────────────────────

def judge_answer(question_id: int, chosen_choice_id: str) -> bool:
    correct = db.get_correct_choice_id(question_id)
    return chosen_choice_id == correct


def submit_answer(
    session_id: int,
    question_id: int,
    chosen_choice_id: str,
    time_spent_sec: Optional[int] = None,
) -> dict:
    """
    채점 후 결과 딕셔너리를 반환한다.
    오답이면 wrong_notes에 자동 기록된다.
    """
    is_correct = judge_answer(question_id, chosen_choice_id)
    db.record_attempt(session_id, question_id, chosen_choice_id, is_correct, time_spent_sec)

    correct_id = db.get_correct_choice_id(question_id)
    choices    = {c["choice_id"]: c["content"] for c in db.get_choices(question_id)}

    return {
        "is_correct":        is_correct,
        "correct_choice_id": correct_id,
        "chosen_choice_id":  chosen_choice_id,
        "correct_content":   choices.get(correct_id, ""),
        "chosen_content":    choices.get(chosen_choice_id, ""),
    }


# ──────────────────────────────────────────────
# 세션 문제 목록 생성
# ──────────────────────────────────────────────

def build_question_list(
    mode: str,
    chapter: Optional[str] = None,
    size: int = DEFAULT_SESSION_SIZE,
) -> list[int]:
    """
    세션에서 풀 문항 id 목록을 생성한다.
    mode: 'all' | 'chapter' | 'review' | 'recommend'
    """
    if mode == "recommend":
        return _recommend_question_ids(size)

    rows = db.get_questions_by_filter(mode=mode, chapter=chapter, limit=size)
    return [r["id"] for r in rows]


def _recommend_question_ids(size: int) -> list[int]:
    """오답 기록을 기반으로 유사문항을 추천한다."""
    wrong_rows  = db.get_wrong_notes(show_mastered=False)
    wrong_ids   = [r["id"] for r in wrong_rows]           # wrong_notes.question_id
    wrong_q_ids = [r["question_id"] for r in wrong_rows] if wrong_rows else []

    if not wrong_q_ids:
        # 오답 없으면 전체 랜덤
        rows = db.get_questions_by_filter(mode="all", limit=size)
        return [r["id"] for r in rows]

    # 오답 문항의 챕터·주제·유형 수집
    ref_questions = []
    for qid in wrong_q_ids[:20]:   # 최근 20개 기준
        row = db.get_question(qid)
        if row:
            ref_questions.append(dict(row))

    candidates = db.get_candidate_questions(exclude_ids=wrong_q_ids)
    scored = _score_candidates(candidates, ref_questions)
    scored.sort(key=lambda x: -x["score"])

    # 상위 N개 중 랜덤 샘플 (단조롭지 않게)
    top = scored[: size * 3]
    random.shuffle(top)
    selected = [c["id"] for c in top[:size]]

    # 부족하면 오답 문항 자체도 섞어 넣음 (재출제 허용)
    if len(selected) < size:
        extra = random.sample(wrong_q_ids, min(size - len(selected), len(wrong_q_ids)))
        selected += extra

    return selected[:size]


def _score_candidates(candidates, ref_questions: list[dict]) -> list[dict]:
    ref_chapter_topic = {(q.get("chapter"), q.get("topic")) for q in ref_questions}
    ref_chapters      = {q.get("chapter") for q in ref_questions}
    ref_types         = {q.get("q_type") for q in ref_questions}

    result = []
    for c in candidates:
        score = 0
        ct    = (c["chapter"], c["topic"])
        if ct in ref_chapter_topic:
            score += SCORE_CHAPTER_TOPIC
        elif c["chapter"] in ref_chapters:
            score += SCORE_CHAPTER_ONLY
        if c["q_type"] in ref_types:
            score += SCORE_QTYPE
        score += c["wrong_count"] * SCORE_WRONG_COUNT
        result.append({"id": c["id"], "score": score})
    return result
