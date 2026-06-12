-- ============================================================
-- Reading Discussion Coach — DB Schema
--   sessions(N) - turns(N개) - reflections(1) 의 1:N:1 구조로
--   세션 단위 멀티턴 코칭 운영을 지원한다.
-- ============================================================

-- 1) 책 메타데이터
CREATE TABLE IF NOT EXISTS books (
    book_id     SERIAL PRIMARY KEY,
    rank        INTEGER,
    title       VARCHAR(255) NOT NULL,
    author      VARCHAR(255),
    yes24_url   VARCHAR(512),
    image_url   VARCHAR(512),
    summary     TEXT
);

-- 2) 대화 세션
CREATE TABLE IF NOT EXISTS sessions (
    session_id      VARCHAR(64) PRIMARY KEY,
    user_pseudo_id  VARCHAR(64) NOT NULL,
    book_id         INTEGER REFERENCES books(book_id),
    coaching_style  VARCHAR(8)  NOT NULL DEFAULT 'v2',   -- v1=Neutral / v2=Inquiry / v3=Challenger
    started_at      TIMESTAMP   NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMP,
    total_turns     INTEGER     NOT NULL DEFAULT 0,
    total_cost_usd  NUMERIC(12,8) NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_style ON sessions(coaching_style);

-- 3) 개별 메시지(턴) 로그
--   thinking_stage 컬럼은 Function Calling으로 분류된 사고 단계 메타
CREATE TABLE IF NOT EXISTS turns (
    turn_id         BIGSERIAL PRIMARY KEY,
    session_id      VARCHAR(64) REFERENCES sessions(session_id) ON DELETE CASCADE,
    turn_index      INTEGER NOT NULL,            -- 세션 내 순서 (0, 1, 2...)
    role            VARCHAR(16) NOT NULL,        -- 'user' or 'assistant'
    content         TEXT NOT NULL,
    thinking_stage  VARCHAR(32),                 -- 'observation' | 'interpretation' | 'evaluation' | 'application' | NULL
    latency_ms      INTEGER,
    cost_usd        NUMERIC(12,8),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, turn_index);

-- 4) 회고문 — 세션 종료 시 자동 생성된 사고 요약
CREATE TABLE IF NOT EXISTS reflections (
    reflection_id   BIGSERIAL PRIMARY KEY,
    session_id      VARCHAR(64) UNIQUE REFERENCES sessions(session_id) ON DELETE CASCADE,
    themes          JSONB,        -- ["성장의 고통", "타인의 시선"]
    open_questions  JSONB,        -- ["내가 진짜 두려워한 것은 무엇이었나"]
    summary_text    TEXT,
    generated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);
