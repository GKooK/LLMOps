"""
PostgreSQL 액세스 계층.
4개 테이블 운영: books / sessions / turns / reflections.
주된 패턴은 키워드 검색이 아니라 "책 1권을 그라운딩"하는 단건 조회.
"""
import os
import time
import json
import psycopg2
import pandas as pd
from psycopg2.extras import RealDictCursor, Json
from typing import List, Dict, Optional


# ────────────────────────────────────────────────────────
# 연결
# ────────────────────────────────────────────────────────
def get_db_connection():
    """5회 재시도 — 컨테이너 부팅 순서 보호"""
    retries = 5
    while retries > 0:
        try:
            return psycopg2.connect(
                host=os.getenv("DB_HOST", "localhost"),
                database=os.getenv("DB_NAME", "books"),
                user=os.getenv("DB_USER", "books_reader"),
                password=os.getenv("DB_PASSWORD", "passwd"),
                port=int(os.getenv("DB_PORT", "5432")),
            )
        except psycopg2.OperationalError:
            retries -= 1
            print(f"DB 연결 실패. 재시도 중... ({retries}회 남음)")
            time.sleep(2)
    raise RuntimeError("DB 연결 실패")


# ────────────────────────────────────────────────────────
# 초기 데이터 적재
# ────────────────────────────────────────────────────────
def init_data_if_empty(csv_path: str = "data/books.csv") -> None:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT to_regclass('public.books');")
        if cur.fetchone()[0] is None:
            print("⚠️ books 테이블이 없습니다. init.sql 적재 실패 가능.")
            return

        cur.execute("SELECT COUNT(*) FROM books")
        if cur.fetchone()[0] > 0:
            print(f"✅ books 데이터 이미 적재되어 있음")
            return

        # 정제본(data/books_clean.csv)이 있으면 우선 사용(중복 제거·정규화 완료).
        # 없으면 원천 books.csv를 견고 파서로 적재 — 원천 파일은 summary 내
        # 비인용 콤마가 있어 표준 pd.read_csv가 깨지므로 robust 로더를 쓴다.
        from src.data_prep import read_books_robust
        clean_path = "data/books_clean.csv"
        if os.path.exists(clean_path):
            df = pd.read_csv(clean_path)
            print(f"📘 정제본 사용: {clean_path}")
        elif os.path.exists(csv_path):
            df = read_books_robust(csv_path)
            print(f"📘 원천 견고 파싱: {csv_path}")
        else:
            print(f"⚠️ {csv_path} 파일이 없습니다.")
            return
        df = df.where(lambda x: x.notnull(), None)
        for _, row in df.iterrows():
            cur.execute(
                """INSERT INTO books (rank, title, author, yes24_url, image_url, summary)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    row.get("rank"),
                    row["title"],
                    row.get("author"),
                    row.get("yes24_url"),
                    row.get("image_url"),
                    row.get("summary"),
                ),
            )
        conn.commit()
        print(f"✅ books {len(df)}건 적재 완료")
    except Exception as e:
        print(f"⚠️ 데이터 초기화 오류: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


# ────────────────────────────────────────────────────────
# books — 책 단건 조회 (세션 시작 시 그라운딩)
# ────────────────────────────────────────────────────────
def find_book(query: str) -> Optional[Dict]:
    """
    제목 또는 저자에 부분 일치하는 책 1권을 반환.
    ILIKE 패턴 매칭으로 첫 매치를 반환.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        pattern = f"%{query.strip()}%"
        cur.execute(
            """SELECT book_id, title, author, summary, yes24_url, image_url
               FROM books
               WHERE title ILIKE %s OR author ILIKE %s
               ORDER BY rank NULLS LAST
               LIMIT 1""",
            (pattern, pattern),
        )
        return cur.fetchone()
    finally:
        if conn:
            conn.close()


# ────────────────────────────────────────────────────────
# sessions
# ────────────────────────────────────────────────────────
def create_session(session_id: str, user_pseudo_id: str, book_id: int, coaching_style: str) -> None:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO sessions (session_id, user_pseudo_id, book_id, coaching_style)
               VALUES (%s, %s, %s, %s)""",
            (session_id, user_pseudo_id, book_id, coaching_style),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


def get_session(session_id: str) -> Optional[Dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT s.*, b.title AS book_title, b.author AS book_author, b.summary AS book_summary
               FROM sessions s
               JOIN books b ON s.book_id = b.book_id
               WHERE s.session_id = %s""",
            (session_id,),
        )
        return cur.fetchone()
    finally:
        if conn:
            conn.close()


def update_session_totals(session_id: str, add_cost: float, ended: bool = False) -> None:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if ended:
            cur.execute(
                """UPDATE sessions
                   SET total_cost_usd = total_cost_usd + %s,
                       total_turns    = (SELECT COUNT(*) FROM turns WHERE session_id = %s AND role='user'),
                       ended_at       = NOW()
                   WHERE session_id = %s""",
                (add_cost, session_id, session_id),
            )
        else:
            cur.execute(
                """UPDATE sessions
                   SET total_cost_usd = total_cost_usd + %s,
                       total_turns    = (SELECT COUNT(*) FROM turns WHERE session_id = %s AND role='user')
                   WHERE session_id = %s""",
                (add_cost, session_id, session_id),
            )
        conn.commit()
    finally:
        if conn:
            conn.close()


# ────────────────────────────────────────────────────────
# turns
# ────────────────────────────────────────────────────────
def insert_turn(
    session_id: str,
    turn_index: int,
    role: str,
    content: str,
    thinking_stage: Optional[str] = None,
    latency_ms: Optional[int] = None,
    cost_usd: Optional[float] = None,
) -> int:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO turns (session_id, turn_index, role, content, thinking_stage, latency_ms, cost_usd)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING turn_id""",
            (session_id, turn_index, role, content, thinking_stage, latency_ms, cost_usd),
        )
        turn_id = cur.fetchone()[0]
        conn.commit()
        return turn_id
    finally:
        if conn:
            conn.close()


def list_turns(session_id: str) -> List[Dict]:
    """세션의 모든 메시지를 시간 순으로 반환."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT turn_index, role, content, thinking_stage
               FROM turns
               WHERE session_id = %s
               ORDER BY turn_index ASC""",
            (session_id,),
        )
        return list(cur.fetchall())
    finally:
        if conn:
            conn.close()


def next_turn_index(session_id: str) -> int:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(turn_index), -1) + 1 FROM turns WHERE session_id = %s",
            (session_id,),
        )
        return int(cur.fetchone()[0])
    finally:
        if conn:
            conn.close()


# ────────────────────────────────────────────────────────
# reflections
# ────────────────────────────────────────────────────────
def save_reflection(session_id: str, themes: List[str], open_questions: List[str], summary_text: str) -> None:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO reflections (session_id, themes, open_questions, summary_text)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (session_id) DO UPDATE
                   SET themes         = EXCLUDED.themes,
                       open_questions = EXCLUDED.open_questions,
                       summary_text   = EXCLUDED.summary_text,
                       generated_at   = NOW()""",
            (session_id, Json(themes), Json(open_questions), summary_text),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


# ────────────────────────────────────────────────────────
# 운영 패널용 집계
# ────────────────────────────────────────────────────────
def list_sessions_recent(limit: int = 30) -> List[Dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT s.session_id, b.title AS book_title, s.coaching_style,
                      s.total_turns, s.total_cost_usd,
                      s.started_at, s.ended_at
               FROM sessions s
               JOIN books b ON s.book_id = b.book_id
               ORDER BY s.started_at DESC
               LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()
        # JSON 직렬화를 위해 datetime을 문자열로
        for r in rows:
            r["started_at"] = r["started_at"].isoformat() if r["started_at"] else None
            r["ended_at"] = r["ended_at"].isoformat() if r["ended_at"] else None
            r["total_cost_usd"] = float(r["total_cost_usd"]) if r["total_cost_usd"] is not None else 0.0
        return rows
    finally:
        if conn:
            conn.close()


def style_aggregate_stats() -> List[Dict]:
    """코칭 스타일별 평균 턴 수·비용 — A/B 결과 비교의 핵심 집계"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT coaching_style,
                      COUNT(*) AS n_sessions,
                      ROUND(AVG(total_turns)::numeric, 2) AS avg_turns,
                      ROUND(AVG(total_cost_usd)::numeric, 6) AS avg_cost_usd
               FROM sessions
               WHERE ended_at IS NOT NULL
               GROUP BY coaching_style
               ORDER BY coaching_style"""
        )
        return list(cur.fetchall())
    finally:
        if conn:
            conn.close()
