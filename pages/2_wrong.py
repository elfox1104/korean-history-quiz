"""
오답노트 페이지.
틀린 문항 목록 조회, 해설 보기, 재풀기 기능.
"""
import json
from pathlib import Path

import streamlit as st

import app.db as db
import app.quiz_engine as engine
from config import resolve_image_path

st.title("❌ 오답노트")

# ──────────────────────────────────────────────
# 필터 바
# ──────────────────────────────────────────────

col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    chapters = ["전체"] + db.get_chapters()
    sel_chapter = st.selectbox("챕터", chapters)
with col2:
    show_mastered = st.checkbox("마스터 문항 포함", value=False)
with col3:
    st.markdown("")  # 높이 맞춤
    refresh = st.button("🔄 새로고침")

chapter_filter = None if sel_chapter == "전체" else sel_chapter
rows = db.get_wrong_notes(chapter=chapter_filter, show_mastered=show_mastered)

# ──────────────────────────────────────────────
# 헤더 요약
# ──────────────────────────────────────────────

total_wrong    = len(rows)
mastered_count = sum(1 for r in rows if r["is_mastered"])
st.caption(f"오답 {total_wrong}개  |  마스터 {mastered_count}개")

if not rows:
    st.info("오답 문항이 없습니다. 먼저 문제를 풀어보세요! 🎉")
    st.stop()

st.divider()

# ──────────────────────────────────────────────
# 문항 카드 목록
# ──────────────────────────────────────────────

for r in rows:
    q_id    = r["question_id"] if "question_id" in r.keys() else r["id"]
    # wrong_notes join 결과에서 question id 추출
    # get_wrong_notes 가 q.id를 반환하므로 r["id"] 사용
    try:
        q_id = r["id"]
    except Exception:
        continue

    q_row = db.get_question(q_id)
    if not q_row:
        continue

    # 최근 5회 이력 조회
    with db.get_conn() as conn:
        history = conn.execute(
            """SELECT is_correct FROM attempts
               WHERE question_id=? ORDER BY attempted_at DESC LIMIT 5""",
            (q_id,),
        ).fetchall()
    history_icons = "".join("✅" if h["is_correct"] else "❌" for h in history)

    mastered_badge = " 🏆" if r["is_mastered"] else ""
    chapter_tag    = f"{r['chapter']}" if r["chapter"] else "미분류"
    topic_tag      = f" > {r['topic']}" if r["topic"] else ""

    with st.expander(
        f"**{chapter_tag}{topic_tag}**  — 오답 {r['wrong_count']}회  {history_icons}{mastered_badge}"
    ):
        st.markdown(q_row["content"])

        # 이미지
        if q_row["image_paths"]:
            try:
                for p in json.loads(q_row["image_paths"]):
                    img_path = resolve_image_path(p)
                    if img_path.exists():
                        st.image(str(img_path), use_container_width=True)
            except Exception:
                pass

        # 보기 + 정답 표시
        choices = db.get_choices(q_id)
        correct_id = q_row["correct_choice_id"]
        markers = ["①", "②", "③", "④", "⑤"]
        for i, c in enumerate(choices):
            icon = "✅ " if c["choice_id"] == correct_id else "　 "
            st.markdown(f"{icon}{markers[i]} {c['content']}")

        # 해설
        if q_row["explanation"]:
            st.info(f"💡 {q_row['explanation']}")

        # 재풀기 버튼
        if st.button("🔁 이 문제 다시 풀기", key=f"retry_{q_id}"):
            # 문제풀기 세션으로 단일 문항 전환
            sid = db.create_session("review", chapter_filter)
            st.session_state["qp_session_id"] = sid
            st.session_state["qp_q_ids"]      = [q_id]
            st.session_state["qp_idx"]        = 0
            st.session_state["qp_score"]      = [0, 0]
            st.session_state["qp_choices"]    = engine.get_shuffled_choices(q_id)
            st.session_state["qp_submitted"]  = False
            st.session_state["qp_result"]     = None
            import time
            st.session_state["qp_start_time"] = time.time()
            st.switch_page("pages/1_quiz.py")

    st.divider()
