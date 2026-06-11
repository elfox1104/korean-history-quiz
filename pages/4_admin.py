"""
관리자 페이지.
- PDF 업로드 → 자동 추출 파이프라인 실행
- 검수 JSON 다운로드 / 업로드
- 문항 is_verified 일괄 승인
- DB 현황 및 초기화
"""
import json
import os
import shutil
from pathlib import Path

import streamlit as st

import app.db as db
from config import (
    RAW_DIR, EXTRACTED_DIR, IMAGES_DIR, DB_PATH,
    RAW_JSON_PATH, REVIEWED_JSON_PATH, SAMPLE_JSON_PATH,
)

st.title("⚙️ 관리자")

# ──────────────────────────────────────────────
# DB 현황
# ──────────────────────────────────────────────

st.subheader("DB 현황")
total    = db.get_question_count(verified_only=False)
verified = db.get_question_count(verified_only=True)
overall  = db.get_stats_overall()

col1, col2, col3 = st.columns(3)
col1.metric("전체 문항",     f"{total}개")
col2.metric("검증 완료",     f"{verified}개")
col3.metric("총 풀이 수",    f"{overall['total']}회")

st.divider()

# ──────────────────────────────────────────────
# 1. 샘플 데이터 적재
# ──────────────────────────────────────────────

st.subheader("1. 샘플 데이터 적재 (PDF 없이 테스트)")

if st.button("📥 샘플 10문항 적재"):
    from pipeline.importer import run_sample_import
    with st.spinner("샘플 데이터 적재 중..."):
        run_sample_import()
    st.success("샘플 데이터가 적재되었습니다. (10문항, is_verified=1)")
    st.rerun()

st.divider()

# ──────────────────────────────────────────────
# 2. PDF 업로드 & 추출
# ──────────────────────────────────────────────

st.subheader("2. PDF 업로드 & 자동 추출")
st.caption("문제지 + 답지 PDF를 올리면 자동 처리됩니다. "
           "텍스트 PDF는 빠르게 추출(텍스트 보기), 스캔 PDF는 OCR(이미지 보기)로 분기됩니다.")

col_q, col_a = st.columns(2)
with col_q:
    q_file = st.file_uploader("문제지 PDF ✱", type="pdf", key="up_q")
with col_a:
    a_file = st.file_uploader("답지 PDF ✱", type="pdf", key="up_a")

if st.button("🚀 자동 추출 & DB 적재", type="primary",
             disabled=(q_file is None or a_file is None)):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    q_path = RAW_DIR / q_file.name
    a_path = RAW_DIR / a_file.name
    q_path.write_bytes(q_file.read())
    a_path.write_bytes(a_file.read())

    progress_bar = st.progress(0.0)
    status_text  = st.empty()

    def on_progress(ratio: float, msg: str):
        progress_bar.progress(min(ratio, 1.0))
        status_text.text(msg)

    from pipeline.text_pdf_pipeline import has_text_layer, run_text_pipeline
    from pipeline.auto_pipeline import run_auto_pipeline
    try:
        if has_text_layer(q_path):
            status_text.text("📄 텍스트 PDF 감지 — 빠른 추출 시작")
            total, has_ans = run_text_pipeline(q_path, a_path, progress_cb=on_progress)
            mode_msg = "텍스트 추출"
        else:
            try:
                import easyocr  # noqa: F401  (설치 여부만 확인)
            except ImportError:
                progress_bar.empty()
                st.error("🖼️ 스캔 PDF는 OCR이 필요합니다. OCR(easyocr)은 로컬 환경에서만 지원됩니다. "
                         "텍스트 PDF를 올리거나, 로컬에서 적재 후 DB를 커밋해 주세요.")
                st.stop()
            status_text.text("🖼️ 스캔 PDF 감지 — OCR 추출(다소 느림)")
            total, has_ans = run_auto_pipeline(q_path, a_path, progress_cb=on_progress)
            mode_msg = "OCR 추출"
        progress_bar.progress(1.0)
        st.success(f"✅ 완료! ({mode_msg}) {total}개 문항 적재 · 정답 확인 {has_ans}개")
        st.rerun()
    except Exception as e:
        st.error(f"오류: {e}")
        raise

st.divider()

# ──────────────────────────────────────────────
# 3. 검수 JSON 다운로드 / 업로드
# ──────────────────────────────────────────────

st.subheader("3. 검수 JSON 관리")

col_dl, col_ul = st.columns(2)
with col_dl:
    if REVIEWED_JSON_PATH.exists():
        st.download_button(
            "⬇️ 검수 JSON 다운로드",
            data=REVIEWED_JSON_PATH.read_text(encoding="utf-8"),
            file_name="questions_reviewed.json",
            mime="application/json",
        )
    else:
        st.caption("검수 파일 없음")

with col_ul:
    up_json = st.file_uploader("검수 완료 JSON 업로드", type="json", key="up_json")
    if up_json and st.button("💾 업로드 저장"):
        EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
        REVIEWED_JSON_PATH.write_bytes(up_json.read())
        st.success("저장 완료. 아래에서 DB 적재를 실행하세요.")

st.divider()

# ──────────────────────────────────────────────
# 4. DB 적재
# ──────────────────────────────────────────────

st.subheader("4. DB 적재")

json_to_import = st.radio(
    "적재할 파일",
    ["검수 완료 JSON (questions_reviewed.json)", "직접 선택"],
    key="import_choice",
)

custom_path = None
if json_to_import == "직접 선택":
    custom_json = st.file_uploader("JSON 파일", type="json", key="up_custom")
    if custom_json:
        tmp = EXTRACTED_DIR / "import_tmp.json"
        tmp.write_bytes(custom_json.read())
        custom_path = tmp

if st.button("📤 DB 적재 실행"):
    from pipeline.importer import run_import
    target = custom_path or REVIEWED_JSON_PATH
    if not target or not target.exists():
        st.error("적재할 파일이 없습니다.")
    else:
        with st.spinner("적재 중..."):
            try:
                run_import(target)
                st.success("DB 적재 완료!")
                st.rerun()
            except Exception as e:
                st.error(f"적재 오류: {e}")

st.divider()

# ──────────────────────────────────────────────
# 5. 일괄 검증 승인
# ──────────────────────────────────────────────

st.subheader("5. 미검증 문항 일괄 승인")
st.caption("is_verified=0 인 문항을 모두 1로 변경합니다. PDF 추출 후 빠른 테스트용.")

if st.button("✅ 전체 승인"):
    with db.get_conn() as conn:
        cnt = conn.execute(
            "UPDATE questions SET is_verified=1 WHERE is_verified=0"
        ).rowcount
    st.success(f"{cnt}개 문항을 승인했습니다.")
    st.rerun()

st.divider()

# ──────────────────────────────────────────────
# 6. DB 초기화 (위험)
# ──────────────────────────────────────────────

st.subheader("6. 데이터 초기화 ⚠️")

with st.expander("위험: 데이터 초기화"):
    confirm = st.text_input("초기화하려면 **DELETE** 를 입력하세요")
    if st.button("🗑️ 전체 초기화", type="primary"):
        if confirm == "DELETE":
            if DB_PATH.exists():
                DB_PATH.unlink()
            db.init_db()
            # 이미지 폴더 초기화
            if IMAGES_DIR.exists():
                shutil.rmtree(IMAGES_DIR)
            IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            st.success("초기화 완료. 페이지를 새로고침하세요.")
            st.rerun()
        else:
            st.error("DELETE 를 정확히 입력해야 합니다.")
