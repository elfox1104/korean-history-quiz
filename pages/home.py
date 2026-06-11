import streamlit as st
from app.db import get_question_count, get_stats_overall

st.title("🏛️ 한국사능력검정시험 오답노트")

total    = get_question_count()
overall  = get_stats_overall()

col1, col2, col3 = st.columns(3)
col1.metric("전체 문항",  f"{total}개")
col2.metric("총 풀이 수", f"{overall['total']}회")
col3.metric("전체 정답률", f"{overall['rate']}%")

st.markdown("""
---
왼쪽 사이드바에서 메뉴를 선택하세요.

| 메뉴 | 설명 |
|------|------|
| 📝 문제풀기 | 챕터별·전체·오답·추천 모드로 문제 풀기 |
| ❌ 오답노트 | 틀린 문제 목록 조회 및 재풀기 |
| 📊 학습통계 | 챕터별 정답률 및 학습 현황 |
| ⚙️ 관리자 | PDF 업로드, 데이터 적재, 문항 검수 |
""")
