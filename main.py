"""
Streamlit 진입점.
실행: python -m streamlit run main.py
"""
import streamlit as st
import streamlit.components.v1 as components
from app.db import init_db

st.set_page_config(
    page_title="한국사능력검정시험 오답노트",
    page_icon="🏛️",
    layout="centered",
    initial_sidebar_state="expanded",
)

# 크롬 자동번역 차단: 페이지 언어를 한국어로 명시하고 notranslate 메타 삽입.
# (이 처리가 없으면 "정답입니다!" 같은 문구가 "번역입니다!"로 잘못 번역됨)
components.html(
    """
    <script>
    try {
        const doc = window.parent.document;
        doc.documentElement.lang = 'ko';
        doc.documentElement.setAttribute('translate', 'no');
        if (!doc.querySelector('meta[name="google"]')) {
            const m = doc.createElement('meta');
            m.name = 'google';
            m.content = 'notranslate';
            doc.head.appendChild(m);
        }
    } catch (e) {}
    </script>
    """,
    height=0,
)

# DB 초기화 (최초 1회)
init_db()

# 페이지 명시 등록 (Streamlit 1.36+ 방식)
home   = st.Page("pages/home.py",  title="홈",      icon="🏛️", default=True)
quiz   = st.Page("pages/1_quiz.py",  title="문제풀기", icon="📝")
wrong  = st.Page("pages/2_wrong.py", title="오답노트", icon="❌")
stats  = st.Page("pages/3_stats.py", title="학습통계", icon="📊")
admin  = st.Page("pages/4_admin.py", title="관리자",   icon="⚙️")

pg = st.navigation([home, quiz, wrong, stats, admin])
pg.run()
