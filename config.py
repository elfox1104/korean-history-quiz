from pathlib import Path

BASE_DIR = Path(__file__).parent

# 데이터 경로
DATA_DIR      = BASE_DIR / "data"
RAW_DIR       = DATA_DIR / "raw"
EXTRACTED_DIR = DATA_DIR / "extracted"
IMAGES_DIR    = DATA_DIR / "images"

# DB
DB_PATH = BASE_DIR / "db" / "quiz.db"

# 추출 결과 파일
RAW_JSON_PATH      = EXTRACTED_DIR / "questions_raw.json"
REVIEWED_JSON_PATH = EXTRACTED_DIR / "questions_reviewed.json"
SAMPLE_JSON_PATH   = EXTRACTED_DIR / "sample_questions.json"

# 유사문항 추천 가중치
SCORE_CHAPTER_TOPIC = 30
SCORE_CHAPTER_ONLY  = 20
SCORE_QTYPE         = 10
SCORE_WRONG_COUNT   = 5   # wrong_count 1회당
SCORE_TODAY_PENALTY = -50

# 마스터 판정: 연속 N회 정답
MASTERY_STREAK = 2

# 한 세션에서 출제할 기본 문항 수
DEFAULT_SESSION_SIZE = 20

# 챕터 키워드 매핑 (분류기에서 사용)
CHAPTER_KEYWORDS: dict[str, list[str]] = {
    "선사시대":    ["구석기", "신석기", "청동기", "철기", "빗살무늬", "주먹도끼", "고인돌", "비파형"],
    "고조선":      ["단군", "위만", "8조법", "고조선", "범금8조"],
    "삼국시대":    ["고구려", "백제", "신라", "가야", "광개토", "장수왕", "근초고왕", "진흥왕", "삼국"],
    "남북국시대":  ["통일신라", "발해", "대조영", "무열왕", "문무왕", "선덕여왕"],
    "고려시대":    ["고려", "왕건", "무신", "정중부", "최충헌", "삼별초", "몽골", "원나라", "공민왕"],
    "조선시대":    ["조선", "태조", "세종", "임진왜란", "병자호란", "붕당", "사화", "한양", "경복궁"],
    "개항기":      ["강화도조약", "갑신정변", "동학", "갑오개혁", "을미사변", "아관파천", "독립협회"],
    "일제강점기":  ["일제", "3·1운동", "독립운동", "임시정부", "신간회", "의열단", "광복군"],
    "현대":        ["광복", "분단", "6·25", "이승만", "박정희", "민주화", "4·19", "5·18"],
}
