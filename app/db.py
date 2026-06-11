"""
DB 초기화 및 모든 쿼리 함수.
choice_id 기반으로 정답을 관리하므로 보기 순서와 무관하게 채점이 정확하다.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date
from typing import Optional

from config import DB_PATH, MASTERY_STREAK

# ──────────────────────────────────────────────
# 연결 헬퍼
# ──────────────────────────────────────────────

@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────────
# 초기화
# ──────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS questions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file       TEXT NOT NULL,
    q_number          INTEGER NOT NULL,
    content           TEXT NOT NULL,
    image_paths       TEXT,               -- JSON 배열 문자열
    correct_choice_id TEXT NOT NULL,
    explanation       TEXT,
    chapter           TEXT,
    topic             TEXT,
    q_type            TEXT,
    difficulty        INTEGER DEFAULT 3,
    is_verified       INTEGER DEFAULT 0,
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS choices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    choice_id   TEXT NOT NULL,            -- "c_{q_number:03d}_{seq}" (question 내에서 유일)
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    image_path  TEXT,
    UNIQUE (question_id, choice_id)       -- 같은 question 안에서만 unique
);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mode       TEXT NOT NULL,             -- "chapter" | "all" | "review" | "recommend"
    filter_val TEXT,
    started_at TEXT DEFAULT (datetime('now')),
    ended_at   TEXT
);

CREATE TABLE IF NOT EXISTS attempts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       INTEGER REFERENCES sessions(id),
    question_id      INTEGER REFERENCES questions(id),
    chosen_choice_id TEXT NOT NULL,
    is_correct       INTEGER NOT NULL,
    time_spent_sec   INTEGER,
    attempted_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wrong_notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id     INTEGER NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE,
    wrong_count     INTEGER DEFAULT 1,
    last_wrong_at   TEXT DEFAULT (datetime('now')),
    last_correct_at TEXT,
    is_mastered     INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_choices_qid   ON choices(question_id);
CREATE INDEX IF NOT EXISTS idx_attempts_qid  ON attempts(question_id);
CREATE INDEX IF NOT EXISTS idx_wrong_qid     ON wrong_notes(question_id);
CREATE INDEX IF NOT EXISTS idx_questions_ch  ON questions(chapter);
"""

def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(DDL)


# ──────────────────────────────────────────────
# 문항 쿼리
# ──────────────────────────────────────────────

def get_question(question_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM questions WHERE id = ?", (question_id,)
        ).fetchone()


def get_choices(question_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM choices WHERE question_id = ? ORDER BY id",
            (question_id,),
        ).fetchall()


def get_correct_choice_id(question_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT correct_choice_id FROM questions WHERE id = ?", (question_id,)
        ).fetchone()
        return row["correct_choice_id"] if row else ""


def get_chapters() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT chapter FROM questions WHERE chapter IS NOT NULL AND is_verified=1 ORDER BY chapter"
        ).fetchall()
        return [r["chapter"] for r in rows]


def get_questions_by_filter(
    mode: str,
    chapter: Optional[str] = None,
    exclude_ids: Optional[list[int]] = None,
    limit: int = 9999,
) -> list[sqlite3.Row]:
    """mode: 'all' | 'chapter' | 'review' | 'recommend'"""
    excl = exclude_ids or []
    # NOT IN (NULL) 은 모든 행을 제거하므로, 제외 목록이 없으면 조건 자체를 생략한다
    excl_clause = f"AND q.id NOT IN ({','.join('?' * len(excl))})" if excl else ""

    with get_conn() as conn:
        if mode == "chapter" and chapter:
            rows = conn.execute(
                f"""SELECT q.* FROM questions q
                    WHERE q.chapter = ? AND q.is_verified = 1
                    {excl_clause}
                    ORDER BY RANDOM() LIMIT ?""",
                (chapter, *excl, limit),
            ).fetchall()
        elif mode == "review":
            rows = conn.execute(
                f"""SELECT q.* FROM questions q
                    JOIN wrong_notes wn ON q.id = wn.question_id
                    WHERE wn.is_mastered = 0
                    {excl_clause}
                    ORDER BY wn.wrong_count DESC, RANDOM() LIMIT ?""",
                (*excl, limit),
            ).fetchall()
        else:  # all
            rows = conn.execute(
                f"""SELECT q.* FROM questions q
                    WHERE q.is_verified = 1
                    {excl_clause}
                    ORDER BY RANDOM() LIMIT ?""",
                (*excl, limit),
            ).fetchall()
        return rows


def get_question_count(verified_only: bool = True) -> int:
    with get_conn() as conn:
        cond = "WHERE is_verified = 1" if verified_only else ""
        return conn.execute(f"SELECT COUNT(*) FROM questions {cond}").fetchone()[0]


# ──────────────────────────────────────────────
# 세션 쿼리
# ──────────────────────────────────────────────

def create_session(mode: str, filter_val: Optional[str] = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (mode, filter_val) VALUES (?, ?)",
            (mode, filter_val),
        )
        return cur.lastrowid


def close_session(session_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET ended_at = datetime('now') WHERE id = ?",
            (session_id,),
        )


# ──────────────────────────────────────────────
# 채점 / 오답 쿼리
# ──────────────────────────────────────────────

def record_attempt(
    session_id: int,
    question_id: int,
    chosen_choice_id: str,
    is_correct: bool,
    time_spent_sec: Optional[int] = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO attempts
               (session_id, question_id, chosen_choice_id, is_correct, time_spent_sec)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, question_id, chosen_choice_id, int(is_correct), time_spent_sec),
        )
        if not is_correct:
            conn.execute(
                """INSERT INTO wrong_notes (question_id, wrong_count, last_wrong_at)
                   VALUES (?, 1, datetime('now'))
                   ON CONFLICT(question_id) DO UPDATE SET
                       wrong_count   = wrong_count + 1,
                       last_wrong_at = datetime('now'),
                       is_mastered   = 0""",
                (question_id,),
            )
        else:
            # 연속 MASTERY_STREAK회 정답이면 is_mastered = 1
            conn.execute(
                """INSERT INTO wrong_notes (question_id, wrong_count, last_correct_at)
                   VALUES (?, 0, datetime('now'))
                   ON CONFLICT(question_id) DO UPDATE SET
                       last_correct_at = datetime('now')""",
                (question_id,),
            )
            # 최근 N회 모두 정답인지 확인
            recent = conn.execute(
                """SELECT is_correct FROM attempts
                   WHERE question_id = ?
                   ORDER BY attempted_at DESC LIMIT ?""",
                (question_id, MASTERY_STREAK),
            ).fetchall()
            if len(recent) >= MASTERY_STREAK and all(r["is_correct"] for r in recent):
                conn.execute(
                    "UPDATE wrong_notes SET is_mastered = 1 WHERE question_id = ?",
                    (question_id,),
                )


def get_wrong_notes(chapter: Optional[str] = None, show_mastered: bool = False) -> list[sqlite3.Row]:
    with get_conn() as conn:
        conditions = ["1=1"]
        params: list = []
        if not show_mastered:
            conditions.append("wn.is_mastered = 0")
        if chapter:
            conditions.append("q.chapter = ?")
            params.append(chapter)
        where = " AND ".join(conditions)
        return conn.execute(
            f"""SELECT q.id, q.content, q.chapter, q.topic, q.q_type,
                       q.image_paths, q.correct_choice_id,
                       wn.wrong_count, wn.last_wrong_at, wn.last_correct_at, wn.is_mastered
                FROM wrong_notes wn
                JOIN questions q ON q.id = wn.question_id
                WHERE {where}
                ORDER BY wn.wrong_count DESC, wn.last_wrong_at DESC""",
            params,
        ).fetchall()


# ──────────────────────────────────────────────
# 유사문항 추천 쿼리
# ──────────────────────────────────────────────

def get_candidate_questions(exclude_ids: list[int]) -> list[sqlite3.Row]:
    """오답 기반 유사문항 추천용 후보 전체 조회."""
    excl = exclude_ids or []
    excl_clause = f"AND q.id NOT IN ({','.join('?' * len(excl))})" if excl else ""
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT q.id, q.chapter, q.topic, q.q_type,
                       COALESCE(wn.wrong_count, 0) AS wrong_count
                FROM questions q
                LEFT JOIN wrong_notes wn ON q.id = wn.question_id
                WHERE q.is_verified = 1
                {excl_clause}
                ORDER BY wrong_count DESC""",
            excl,
        ).fetchall()


# ──────────────────────────────────────────────
# 통계 쿼리
# ──────────────────────────────────────────────

def get_stats_overall() -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(is_correct) AS correct
               FROM attempts"""
        ).fetchone()
        total   = row["total"] or 0
        correct = row["correct"] or 0
        return {"total": total, "correct": correct, "rate": round(correct / total * 100, 1) if total else 0}


def get_stats_by_chapter() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT q.chapter,
                      COUNT(*) AS total,
                      SUM(a.is_correct) AS correct
               FROM attempts a
               JOIN questions q ON q.id = a.question_id
               WHERE q.chapter IS NOT NULL
               GROUP BY q.chapter
               ORDER BY q.chapter"""
        ).fetchall()
        result = []
        for r in rows:
            total   = r["total"] or 0
            correct = r["correct"] or 0
            result.append({
                "chapter": r["chapter"],
                "total":   total,
                "correct": correct,
                "rate":    round(correct / total * 100, 1) if total else 0,
            })
        return result


def get_daily_counts(days: int = 7) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT DATE(attempted_at) AS day,
                      COUNT(*) AS total,
                      SUM(is_correct) AS correct
               FROM attempts
               WHERE attempted_at >= DATE('now', ?)
               GROUP BY day
               ORDER BY day""",
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# 임포트 (pipeline → DB)
# ──────────────────────────────────────────────

def upsert_question(q: dict) -> int:
    """
    questions_reviewed.json 한 항목을 DB에 삽입(중복 시 업데이트).
    반환값: question.id
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM questions WHERE source_file=? AND q_number=?",
            (q["source_file"], q["q_number"]),
        ).fetchone()

        image_paths_json = json.dumps(q.get("image_paths") or [], ensure_ascii=False)

        if existing:
            qid = existing["id"]
            conn.execute(
                """UPDATE questions SET
                    content=?, image_paths=?, correct_choice_id=?,
                    explanation=?, chapter=?, topic=?, q_type=?,
                    difficulty=?, is_verified=?
                   WHERE id=?""",
                (
                    q["content"], image_paths_json, q["correct_choice_id"],
                    q.get("explanation"), q.get("chapter"), q.get("topic"),
                    q.get("q_type"), q.get("difficulty", 3), q.get("is_verified", 0),
                    qid,
                ),
            )
            conn.execute("DELETE FROM choices WHERE question_id=?", (qid,))
        else:
            cur = conn.execute(
                """INSERT INTO questions
                   (source_file, q_number, content, image_paths, correct_choice_id,
                    explanation, chapter, topic, q_type, difficulty, is_verified)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    q["source_file"], q["q_number"], q["content"], image_paths_json,
                    q["correct_choice_id"], q.get("explanation"),
                    q.get("chapter"), q.get("topic"), q.get("q_type"),
                    q.get("difficulty", 3), q.get("is_verified", 0),
                ),
            )
            qid = cur.lastrowid

        for c in q.get("choices", []):
            conn.execute(
                """INSERT INTO choices (choice_id, question_id, content, image_path)
                   VALUES (?,?,?,?)
                   ON CONFLICT(question_id, choice_id) DO UPDATE SET
                       content=excluded.content, image_path=excluded.image_path""",
                (c["choice_id"], qid, c["content"], c.get("image_path")),
            )
        return qid
