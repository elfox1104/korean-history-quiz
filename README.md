# 한국사능력검정시험 오답노트 (PoC)

한국사능력검정시험 기출문제를 풀고, 틀린 문제를 오답노트로 관리하며,
오답 기반으로 유사문항을 추천하는 학습 도구입니다.

## 기능
- 챕터별 / 전체 / 오답만 / 추천 문제 풀이
- 보기 순서 랜덤화, 즉시 채점
- 오답노트 자동 기록 및 마스터 판정(연속 정답 시 졸업)
- 학습 통계(챕터별 정답률, 일별 풀이량)
- PDF 자동 추출(텍스트 PDF는 즉시, 스캔 PDF는 OCR)

## 현재 적재된 문항 (259개)
| 회차 | 문항 | 방식 |
|---|---|---|
| 47회 | 50 | 스캔 → OCR(이미지 보기) |
| 71회 | 50 | 텍스트(텍스트 보기) |
| 73회 | 49 | 스캔 → OCR(이미지 보기) |
| 75회 | 50 | 텍스트(텍스트 보기) |
| 77회 | 50 | 텍스트(텍스트 보기) |
| sample | 10 | 샘플 |

## 로컬 실행
```bash
pip install -r requirements.txt
python -m streamlit run main.py
```
스캔 PDF OCR 적재가 필요하면 추가로 `pip install easyocr`.

## Streamlit Community Cloud 배포
1. 이 리포를 GitHub에 푸시
2. https://share.streamlit.io → "New app"
3. 리포 선택, **Main file path: `main.py`**, Python 3.11+ 선택
4. Deploy

> ⚠️ 무료 클라우드는 파일시스템이 휘발성입니다. 적재된 259문항은 읽기 정상이지만,
> 배포본에서 새로 쌓이는 오답·풀이 기록은 재시작 시 초기화됩니다.
> 영구 저장이 필요하면 Turso(libSQL)·Supabase 등 호스팅 DB로 전환하세요.

## 구조
```
main.py              진입점 (st.navigation)
config.py            경로·상수·챕터 키워드
app/db.py            DB 스키마 및 쿼리
app/quiz_engine.py   출제·채점·추천 로직
pages/               홈/문제풀기/오답노트/통계/관리자
pipeline/
  text_pdf_pipeline.py  텍스트 레이어 PDF 추출
  auto_pipeline.py      스캔 PDF OCR 추출(easyocr)
  importer.py           샘플/JSON 적재
db/quiz.db           적재된 문항 DB
data/images/         문항 자료 이미지
```
