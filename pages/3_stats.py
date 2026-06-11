"""
학습통계 페이지.
전체 정답률, 챕터별 정답률, 일별 학습량 시각화.
"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

import app.db as db

st.title("📊 학습통계")

# ──────────────────────────────────────────────
# 전체 통계
# ──────────────────────────────────────────────

overall = db.get_stats_overall()
total, correct, rate = overall["total"], overall["correct"], overall["rate"]

if total == 0:
    st.info("아직 풀이 기록이 없습니다. 문제를 풀어보세요!")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("총 풀이 수",  f"{total}문제")
col2.metric("정답 수",     f"{correct}문제")
col3.metric("전체 정답률", f"{rate}%")

st.divider()

# ──────────────────────────────────────────────
# 챕터별 정답률 (수평 막대)
# ──────────────────────────────────────────────

chapter_stats = db.get_stats_by_chapter()

if chapter_stats:
    st.subheader("챕터별 정답률")
    df_ch = pd.DataFrame(chapter_stats)
    df_ch = df_ch.sort_values("rate", ascending=True)

    fig = px.bar(
        df_ch,
        x="rate",
        y="chapter",
        orientation="h",
        text="rate",
        color="rate",
        color_continuous_scale=["#ef553b", "#ffa15a", "#00cc96"],
        range_color=[0, 100],
        labels={"rate": "정답률(%)", "chapter": "챕터"},
        range_x=[0, 100],
    )
    fig.update_traces(texttemplate="%{text}%", textposition="outside")
    fig.update_layout(
        showlegend=False,
        coloraxis_showscale=False,
        height=max(300, len(df_ch) * 45),
        margin=dict(l=10, r=40, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # 취약 챕터 안내
    weak = df_ch[df_ch["rate"] < 50]
    if not weak.empty:
        st.warning("⚠️ 취약 챕터 (정답률 50% 미만): " + ", ".join(weak["chapter"].tolist()))

st.divider()

# ──────────────────────────────────────────────
# 일별 학습량 (최근 14일)
# ──────────────────────────────────────────────

st.subheader("최근 14일 학습량")
daily = db.get_daily_counts(days=14)

if daily:
    df_d = pd.DataFrame(daily)
    df_d["오답"] = df_d["total"] - df_d["correct"]

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=df_d["day"], y=df_d["correct"],
        name="정답", marker_color="#00cc96",
    ))
    fig2.add_trace(go.Bar(
        x=df_d["day"], y=df_d["오답"],
        name="오답", marker_color="#ef553b",
    ))
    fig2.update_layout(
        barmode="stack",
        xaxis_title="날짜",
        yaxis_title="문항 수",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=300,
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.caption("최근 14일 기록 없음")

st.divider()

# ──────────────────────────────────────────────
# 오답 현황 요약
# ──────────────────────────────────────────────

st.subheader("오답노트 현황")
wrong_rows = db.get_wrong_notes(show_mastered=True)
total_wrong    = len(wrong_rows)
mastered_count = sum(1 for r in wrong_rows if r["is_mastered"])
remaining      = total_wrong - mastered_count

col1, col2, col3 = st.columns(3)
col1.metric("전체 오답",    f"{total_wrong}문제")
col2.metric("마스터 완료",  f"{mastered_count}문제")
col3.metric("복습 필요",    f"{remaining}문제")
