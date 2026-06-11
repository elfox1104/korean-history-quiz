"""
questions_reviewed.json → SQLite DB 적재.

사용:
    python -m pipeline.importer                          # 기본 경로
    python -m pipeline.importer --json data/extracted/questions_reviewed.json
    python -m pipeline.importer --sample                 # 샘플 데이터 생성 후 적재
"""
import argparse
import json
import sys
from pathlib import Path

from config import REVIEWED_JSON_PATH, SAMPLE_JSON_PATH
from app.db import init_db, upsert_question, get_question_count

SAMPLE_DATA = [
    {
        "source_file": "sample.pdf",
        "q_number": 1,
        "content": "다음 유물이 처음 만들어진 시대의 생활 모습으로 옳은 것은?",
        "image_paths": [],
        "choices": [
            {"choice_id": "c_001_1", "content": "반달 돌칼로 벼를 수확하였다.",   "image_path": None},
            {"choice_id": "c_001_2", "content": "철제 농기구로 밭을 갈았다.",      "image_path": None},
            {"choice_id": "c_001_3", "content": "주먹도끼를 사용하여 사냥하였다.", "image_path": None},
            {"choice_id": "c_001_4", "content": "비파형 동검을 제작하였다.",       "image_path": None},
            {"choice_id": "c_001_5", "content": "고인돌을 만들어 무덤으로 사용하였다.", "image_path": None},
        ],
        "answer_seq": 3,
        "correct_choice_id": "c_001_3",
        "chapter": "선사시대", "topic": "구석기", "q_type": "유물분석",
        "difficulty": 2, "is_verified": 1,
        "explanation": "주먹도끼는 구석기 시대의 대표 유물이다. 반달 돌칼은 청동기, 철제 농기구는 철기 시대에 해당한다.",
    },
    {
        "source_file": "sample.pdf",
        "q_number": 2,
        "content": "다음 설명에 해당하는 나라로 옳은 것은? (단군왕검이 건국하였으며, 8조법이 있었다.)",
        "image_paths": [],
        "choices": [
            {"choice_id": "c_002_1", "content": "부여",   "image_path": None},
            {"choice_id": "c_002_2", "content": "고조선", "image_path": None},
            {"choice_id": "c_002_3", "content": "동예",   "image_path": None},
            {"choice_id": "c_002_4", "content": "삼한",   "image_path": None},
            {"choice_id": "c_002_5", "content": "옥저",   "image_path": None},
        ],
        "answer_seq": 2,
        "correct_choice_id": "c_002_2",
        "chapter": "고조선", "topic": "단군왕검", "q_type": "일반",
        "difficulty": 1, "is_verified": 1,
        "explanation": "고조선은 단군왕검이 기원전 2333년에 건국하였다. 사회 질서를 유지하기 위해 8조법을 두었다.",
    },
    {
        "source_file": "sample.pdf",
        "q_number": 3,
        "content": "다음 자료의 밑줄 친 '이 왕'의 업적으로 옳은 것은? '이 왕은 백제를 공격하여 한강 유역을 차지하였다.'",
        "image_paths": [],
        "choices": [
            {"choice_id": "c_003_1", "content": "불교를 공인하였다.",            "image_path": None},
            {"choice_id": "c_003_2", "content": "화랑도를 국가 조직으로 개편하였다.", "image_path": None},
            {"choice_id": "c_003_3", "content": "독서삼품과를 시행하였다.",      "image_path": None},
            {"choice_id": "c_003_4", "content": "골품제를 정비하였다.",          "image_path": None},
            {"choice_id": "c_003_5", "content": "삼국사기를 편찬하였다.",        "image_path": None},
        ],
        "answer_seq": 2,
        "correct_choice_id": "c_003_2",
        "chapter": "삼국시대", "topic": "진흥왕", "q_type": "사료분석",
        "difficulty": 3, "is_verified": 1,
        "explanation": "진흥왕은 한강 유역을 차지하고 화랑도를 국가 조직으로 개편하였다.",
    },
    {
        "source_file": "sample.pdf",
        "q_number": 4,
        "content": "다음 중 고려 무신정변(1170)의 결과로 옳지 않은 것은?",
        "image_paths": [],
        "choices": [
            {"choice_id": "c_004_1", "content": "이의방·정중부 등 무신이 권력을 장악하였다.", "image_path": None},
            {"choice_id": "c_004_2", "content": "문신 중심의 통치 체제가 강화되었다.",        "image_path": None},
            {"choice_id": "c_004_3", "content": "무신 집권자들 사이에 권력 투쟁이 일어났다.", "image_path": None},
            {"choice_id": "c_004_4", "content": "최충헌이 교정도감을 설치하였다.",             "image_path": None},
            {"choice_id": "c_004_5", "content": "명학소의 망이·망소이가 봉기를 일으켰다.",     "image_path": None},
        ],
        "answer_seq": 2,
        "correct_choice_id": "c_004_2",
        "chapter": "고려시대", "topic": "무신정변", "q_type": "일반",
        "difficulty": 3, "is_verified": 1,
        "explanation": "무신정변 이후 무신들이 권력을 장악하면서 문신 중심 체제는 오히려 약화되었다.",
    },
    {
        "source_file": "sample.pdf",
        "q_number": 5,
        "content": "조선 세종 때 편찬된 문화적 업적으로 옳은 것을 모두 고른 것은?",
        "image_paths": [],
        "choices": [
            {"choice_id": "c_005_1", "content": "훈민정음, 측우기",     "image_path": None},
            {"choice_id": "c_005_2", "content": "동국통감, 경국대전",   "image_path": None},
            {"choice_id": "c_005_3", "content": "조선왕조실록, 목민심서", "image_path": None},
            {"choice_id": "c_005_4", "content": "동의보감, 대동여지도", "image_path": None},
            {"choice_id": "c_005_5", "content": "칠정산, 향약집성방",   "image_path": None},
        ],
        "answer_seq": 5,
        "correct_choice_id": "c_005_5",
        "chapter": "조선시대", "topic": "세종대왕", "q_type": "일반",
        "difficulty": 3, "is_verified": 1,
        "explanation": "세종 때 칠정산(역법)과 향약집성방(의학서)이 편찬되었다. 훈민정음과 측우기도 세종 때지만 선택지의 조합이 더 정확한 것은 ⑤이다.",
    },
    {
        "source_file": "sample.pdf",
        "q_number": 6,
        "content": "다음에서 설명하는 사건은? '1894년 동학 교도와 농민들이 전라도 고부에서 시작한 봉기'",
        "image_paths": [],
        "choices": [
            {"choice_id": "c_006_1", "content": "임오군란",    "image_path": None},
            {"choice_id": "c_006_2", "content": "갑신정변",    "image_path": None},
            {"choice_id": "c_006_3", "content": "동학 농민 운동", "image_path": None},
            {"choice_id": "c_006_4", "content": "을미사변",    "image_path": None},
            {"choice_id": "c_006_5", "content": "독립협회 운동", "image_path": None},
        ],
        "answer_seq": 3,
        "correct_choice_id": "c_006_3",
        "chapter": "개항기", "topic": "동학농민운동", "q_type": "사료분석",
        "difficulty": 1, "is_verified": 1,
        "explanation": "1894년 전라도 고부에서 전봉준을 중심으로 동학 농민 운동이 시작되었다.",
    },
    {
        "source_file": "sample.pdf",
        "q_number": 7,
        "content": "다음 선언문을 발표한 단체로 옳은 것은? '우리는 일본 제국주의의 지배에서 벗어나 자유·독립을 선언한다.'",
        "image_paths": [],
        "choices": [
            {"choice_id": "c_007_1", "content": "신민회",           "image_path": None},
            {"choice_id": "c_007_2", "content": "대한민국 임시 정부", "image_path": None},
            {"choice_id": "c_007_3", "content": "독립협회",         "image_path": None},
            {"choice_id": "c_007_4", "content": "의열단",           "image_path": None},
            {"choice_id": "c_007_5", "content": "신간회",           "image_path": None},
        ],
        "answer_seq": 2,
        "correct_choice_id": "c_007_2",
        "chapter": "일제강점기", "topic": "임시정부", "q_type": "사료분석",
        "difficulty": 2, "is_verified": 1,
        "explanation": "대한민국 임시 정부는 1919년 3·1 운동 이후 상하이에서 수립되었다.",
    },
    {
        "source_file": "sample.pdf",
        "q_number": 8,
        "content": "4·19 혁명(1960)의 직접적인 원인으로 옳은 것은?",
        "image_paths": [],
        "choices": [
            {"choice_id": "c_008_1", "content": "5·16 군사 정변",          "image_path": None},
            {"choice_id": "c_008_2", "content": "3·15 부정 선거",          "image_path": None},
            {"choice_id": "c_008_3", "content": "유신 헌법 선포",          "image_path": None},
            {"choice_id": "c_008_4", "content": "한·일 협정 체결",         "image_path": None},
            {"choice_id": "c_008_5", "content": "6월 민주 항쟁",           "image_path": None},
        ],
        "answer_seq": 2,
        "correct_choice_id": "c_008_2",
        "chapter": "현대", "topic": "4·19혁명", "q_type": "일반",
        "difficulty": 2, "is_verified": 1,
        "explanation": "이승만 정권의 3·15 부정 선거에 분노한 학생과 시민이 4·19 혁명을 일으켰다.",
    },
    {
        "source_file": "sample.pdf",
        "q_number": 9,
        "content": "발해에 대한 설명으로 옳은 것은?",
        "image_paths": [],
        "choices": [
            {"choice_id": "c_009_1", "content": "왕건이 건국하였다.",                "image_path": None},
            {"choice_id": "c_009_2", "content": "대조영이 건국하였다.",              "image_path": None},
            {"choice_id": "c_009_3", "content": "신라의 삼국 통일로 멸망하였다.",   "image_path": None},
            {"choice_id": "c_009_4", "content": "고구려와 동일한 영역을 차지하였다.", "image_path": None},
            {"choice_id": "c_009_5", "content": "당나라의 지배를 받았다.",           "image_path": None},
        ],
        "answer_seq": 2,
        "correct_choice_id": "c_009_2",
        "chapter": "남북국시대", "topic": "발해", "q_type": "일반",
        "difficulty": 1, "is_verified": 1,
        "explanation": "발해는 고구려 유민 출신 대조영이 698년에 건국한 나라이다.",
    },
    {
        "source_file": "sample.pdf",
        "q_number": 10,
        "content": "임진왜란(1592) 중 이순신 장군이 거둔 승전으로 옳지 않은 것은?",
        "image_paths": [],
        "choices": [
            {"choice_id": "c_010_1", "content": "한산도 대첩",   "image_path": None},
            {"choice_id": "c_010_2", "content": "명량 대첩",     "image_path": None},
            {"choice_id": "c_010_3", "content": "노량 해전",     "image_path": None},
            {"choice_id": "c_010_4", "content": "행주 대첩",     "image_path": None},
            {"choice_id": "c_010_5", "content": "옥포 해전",     "image_path": None},
        ],
        "answer_seq": 4,
        "correct_choice_id": "c_010_4",
        "chapter": "조선시대", "topic": "임진왜란", "q_type": "일반",
        "difficulty": 2, "is_verified": 1,
        "explanation": "행주 대첩은 권율 장군이 이끈 육군의 승전이다. 이순신은 수군을 지휘하였다.",
    },
]


def load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_import(json_path: Path) -> None:
    init_db()
    questions = load_json(json_path)
    print(f"[importer] {len(questions)}개 문항 적재 시작...")

    ok, skip = 0, 0
    for q in questions:
        try:
            upsert_question(q)
            ok += 1
        except Exception as e:
            print(f"  [SKIP] q_number={q.get('q_number')} 오류: {e}")
            skip += 1

    total = get_question_count(verified_only=False)
    verified = get_question_count(verified_only=True)
    print(f"[importer] done - ok={ok} skip={skip}")
    print(f"           DB total={total} verified={verified}")


def run_sample_import() -> None:
    SAMPLE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAMPLE_JSON_PATH.write_text(
        json.dumps(SAMPLE_DATA, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[importer] 샘플 데이터 생성: {SAMPLE_JSON_PATH}")
    run_import(SAMPLE_JSON_PATH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json",   default=None,  help="적재할 JSON 파일 경로")
    parser.add_argument("--sample", action="store_true", help="샘플 데이터로 테스트")
    args = parser.parse_args()

    if args.sample:
        run_sample_import()
    elif args.json:
        run_import(Path(args.json))
    elif REVIEWED_JSON_PATH.exists():
        run_import(REVIEWED_JSON_PATH)
    else:
        print("[importer] 적재할 파일이 없습니다.")
        print("  --sample  : 샘플 데이터 테스트")
        print("  --json <path>: 직접 지정")
        sys.exit(1)
