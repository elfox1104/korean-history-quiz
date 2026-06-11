"""
문제풀기 페이지.

세션 상태 키:
  qp_session_id   : DB 세션 id
  qp_q_ids        : 출제할 문항 id 목록
  qp_idx          : 현재 문항 인덱스
  qp_choices      : 현재 문항의 섞인 보기 목록
  qp_submitted    : 현재 문항 제출 여부
  qp_result       : 채점 결과 dict
  qp_start_time   : 문항 시작 시각 (time.time())
  qp_score        : (맞은 수, 전체 수)
"""
import json
import time
from pathlib import Path

import streamlit as st

import app.db as db
import app.quiz_engine as engine
from config import DEFAULT_SESSION_SIZE, resolve_image_path

st.title("📝 문제풀기")

# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def reset_session() -> None:
    for key in ["qp_session_id", "qp_q_ids", "qp_idx",
                "qp_choices", "qp_submitted", "qp_result",
                "qp_start_time", "qp_score"]:
        st.session_state.pop(key, None)


def load_question(idx: int) -> None:
    q_id = st.session_state["qp_q_ids"][idx]
    st.session_state["qp_choices"]    = engine.get_shuffled_choices(q_id)
    st.session_state["qp_submitted"]  = False
    st.session_state["qp_result"]     = None
    st.session_state["qp_start_time"] = time.time()


def _show_images(image_paths_json: str) -> bool:
    """이미지를 표시한다. 하나라도 표시되면 True 반환."""
    if not image_paths_json:
        return False
    try:
        paths = json.loads(image_paths_json)
        shown = False
        for p in paths:
            img_path = resolve_image_path(p)
            if img_path.exists():
                st.image(str(img_path), use_container_width=True)
                shown = True
            else:
                st.caption(f"[이미지 없음: {img_path.name}]")
        return shown
    except Exception:
        return False


# ──────────────────────────────────────────────
# 설정 화면
# ──────────────────────────────────────────────

if "qp_q_ids" not in st.session_state:
    total = db.get_question_count()
    if total == 0:
        st.warning("문항 데이터가 없습니다. ⚙️ 관리자 페이지에서 데이터를 먼저 적재해 주세요.")
        st.stop()

    st.subheader("학습 설정")

    mode = st.radio(
        "출제 모드",
        ["전체 문제", "챕터별", "오답만", "추천 문제"],
        horizontal=True,
    )

    chapter = None
    if mode == "챕터별":
        chapters = db.get_chapters()
        if not chapters:
            st.warning("챕터 정보가 없습니다.")
            st.stop()
        chapter = st.selectbox("챕터 선택", chapters)

    size = st.slider("출제 문항 수", min_value=5, max_value=min(50, total),
                     value=min(DEFAULT_SESSION_SIZE, total), step=5)

    if st.button("▶ 시작하기", type="primary"):
        mode_map = {"전체 문제": "all", "챕터별": "chapter", "오답만": "review", "추천 문제": "recommend"}
        q_ids = engine.build_question_list(mode=mode_map[mode], chapter=chapter, size=size)

        if not q_ids:
            st.error("출제할 문항이 없습니다. 조건을 변경하거나 데이터를 추가해 주세요.")
            st.stop()

        st.session_state["qp_session_id"] = db.create_session(mode_map[mode], chapter)
        st.session_state["qp_q_ids"]      = q_ids
        st.session_state["qp_idx"]        = 0
        st.session_state["qp_score"]      = [0, 0]
        load_question(0)
        st.rerun()

    st.stop()


# ──────────────────────────────────────────────
# 문제 풀기 화면
# ──────────────────────────────────────────────

q_ids      = st.session_state["qp_q_ids"]
idx        = st.session_state["qp_idx"]
total_q    = len(q_ids)
session_id = st.session_state["qp_session_id"]
score      = st.session_state["qp_score"]

if idx >= total_q:
    db.close_session(session_id)
    correct, total_tried = score
    rate = round(correct / total_tried * 100) if total_tried else 0
    st.success(f"🎉 세션 완료!  정답률 **{rate}%** ({correct}/{total_tried})")
    if st.button("다시 시작"):
        reset_session()
        st.rerun()
    st.stop()

q_id    = q_ids[idx]
q_row   = db.get_question(q_id)
choices = st.session_state["qp_choices"]

markers = ["①", "②", "③", "④", "⑤"]
_is_image_mode = choices and choices[0]["content"].startswith("① ② ③ ④ 중")

# ── 진행 바 ──
st.progress(idx / total_q, text=f"문제 {idx+1} / {total_q}  |  정답 {score[0]}개")

# ── 챕터 태그 ──
meta_parts = []
if q_row["chapter"]: meta_parts.append(q_row["chapter"])
if q_row["topic"]:   meta_parts.append(q_row["topic"])
if meta_parts:
    st.caption(" > ".join(meta_parts))

st.divider()

# ──────────────────────────────────────────────
# 문제 표시
# ──────────────────────────────────────────────

# 문제 번호(세션 진행 순서) + 질문 텍스트.
# 원래 시험지 번호(q_number)가 아니라 세션 내 순번(idx+1)을 써서
# 상단 "문제 N/총개수" 진행 표시와 번호가 일치하도록 한다.
st.markdown(f"### {idx + 1}. {q_row['content']}")

# 설명(자료/그림) 이미지 — 있을 때만
has_image = _show_images(q_row["image_paths"])

st.markdown("")

# ──────────────────────────────────────────────
# 보기 출력 (미제출)
# ──────────────────────────────────────────────

if not st.session_state["qp_submitted"]:

    if _is_image_mode:
        # 이미지 속 ①②③④는 고정 순서이므로 셔플하지 않고 seq 순서로 버튼 배치
        st.caption("위 이미지에서 보기를 확인한 후 정답 번호를 클릭하세요.")
        ordered = sorted(choices, key=lambda c: int(c["choice_id"].split("_")[-1]))
        cols = st.columns(len(ordered))
        for i, c in enumerate(ordered):
            seq = int(c["choice_id"].split("_")[-1])
            with cols[i]:
                if st.button(markers[seq - 1], key=f"btn_{idx}_{seq}", use_container_width=True):
                    elapsed = int(time.time() - st.session_state["qp_start_time"])
                    result  = engine.submit_answer(session_id, q_id, c["choice_id"], elapsed)
                    st.session_state["qp_result"]    = result
                    st.session_state["qp_submitted"] = True
                    if result["is_correct"]:
                        st.session_state["qp_score"][0] += 1
                    st.session_state["qp_score"][1] += 1
                    st.rerun()

    else:
        # 텍스트 모드: 라디오 버튼
        choice_labels = [f"{markers[i]} {c['content']}" for i, c in enumerate(choices)]
        choice_ids    = [c["choice_id"] for c in choices]

        selected_label = st.radio("보기를 선택하세요", choice_labels, index=None, key=f"radio_{idx}")

        for i, c in enumerate(choices):
            if c.get("image_path"):
                p = resolve_image_path(c["image_path"])
                if p.exists():
                    st.image(str(p), caption=markers[i], width=200)

        col1, _ = st.columns([1, 3])
        with col1:
            if st.button("제출", disabled=selected_label is None, type="primary"):
                chosen_idx       = choice_labels.index(selected_label)
                chosen_choice_id = choice_ids[chosen_idx]
                elapsed          = int(time.time() - st.session_state["qp_start_time"])
                result = engine.submit_answer(session_id, q_id, chosen_choice_id, elapsed)
                st.session_state["qp_result"]    = result
                st.session_state["qp_submitted"] = True
                if result["is_correct"]:
                    st.session_state["qp_score"][0] += 1
                st.session_state["qp_score"][1] += 1
                st.rerun()


# ──────────────────────────────────────────────
# 채점 결과
# ──────────────────────────────────────────────

else:
    result     = st.session_state["qp_result"]
    correct_id = result["correct_choice_id"]

    if _is_image_mode:
        correct_seq    = correct_id.split("_")[-1] if correct_id else "?"
        correct_marker = markers[int(correct_seq) - 1] if correct_seq.isdigit() else correct_seq

        if result["is_correct"]:
            st.success(f"✅ 정답입니다! (정답: {correct_marker})")
        else:
            # 선택한 번호 추출: choice_id = c_XXX_N → N번째 markers
            chosen_seq    = result.get("chosen_choice_id", "").split("_")[-1]
            chosen_marker = markers[int(chosen_seq) - 1] if chosen_seq.isdigit() else "?"
            st.error(f"❌ 오답입니다.  내가 선택: {chosen_marker}  /  정답: **{correct_marker}**")

    else:
        for i, c in enumerate(choices):
            if c["choice_id"] == correct_id:
                st.markdown(f"✅ **{markers[i]} {c['content']}**")
            else:
                st.markdown(f"　　{markers[i]} {c['content']}")
        st.divider()
        if result["is_correct"]:
            st.success("✅ 정답입니다!")
        else:
            st.error(f"❌ 오답입니다.  정답: **{result['correct_content']}**")

    if q_row["explanation"]:
        with st.expander("💡 해설 보기"):
            st.write(q_row["explanation"])

    st.markdown("")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("다음 문제 →", type="primary"):
            st.session_state["qp_idx"] += 1
            if st.session_state["qp_idx"] < total_q:
                load_question(st.session_state["qp_idx"])
            st.rerun()
    with col2:
        if st.button("세션 종료"):
            db.close_session(session_id)
            reset_session()
            st.rerun()
