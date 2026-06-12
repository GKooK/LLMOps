"""
FastAPI 진입점.

엔드포인트:
  POST /session/start  → 세션 생성 + 책 그라운딩 + AI 첫 인사
  POST /session/turn   → 1턴 진행 (메모리 압축 + 함수 호출 + 답변)
  POST /session/end    → 세션 종료 + 자동 회고문 생성

운영 패널:
  GET  /ops/sessions   → 최근 세션 목록
  GET  /ops/styles     → 코칭 스타일별 집계 (A/B 결과 비교)
"""
import os
import json
import uuid
import pandas as pd
from datetime import datetime
from fastapi import FastAPI, HTTPException

from src.models import (
    StartSessionRequest, StartSessionResponse,
    TurnRequest, TurnResponse,
    EndSessionRequest, EndSessionResponse, Reflection,
)
from src import database as db
from src.llm_engine import LLMEngine
from src.memory import build_context_messages, render_full_dialogue
from src.security import (
    mask_pii, check_unsafe_content, safety_gate, CRISIS_RESPONSE_KO,
)

import yaml

# ────────── 부팅 ──────────
app = FastAPI(title="Reading Discussion Coach API", version="0.1.0")
engine = LLMEngine()

with open("configs/model.yaml", "r", encoding="utf-8") as f:
    _cfg = yaml.safe_load(f)
MEM_RECENT_KEEP = _cfg["memory"]["recent_keep_turns"]
MEM_TRIGGER_AT = _cfg["memory"]["trigger_compaction_at"]


# ────────── 로그 ──────────
LOG_PATH = "logs/turns.csv"
os.makedirs("logs", exist_ok=True)
if not os.path.exists(LOG_PATH):
    pd.DataFrame(columns=[
        "timestamp", "session_id", "turn_index", "role",
        "coaching_style", "thinking_stage",
        "latency_ms", "cost_usd", "memory_compacted", "status",
    ]).to_csv(LOG_PATH, index=False)


def _log_turn(**kw) -> None:
    pd.DataFrame([kw]).to_csv(LOG_PATH, mode="a", header=False, index=False)


# ────────── 시작 시 DB 자동 적재 ──────────
@app.on_event("startup")
def _startup():
    db.init_data_if_empty()


# ────────── Health ──────────
@app.get("/health")
def health():
    return {"status": "ok"}


# ──────────────────────────────────────────────────────
# 1) 세션 시작
# ──────────────────────────────────────────────────────
@app.post("/session/start", response_model=StartSessionResponse)
def start_session(req: StartSessionRequest):
    if check_unsafe_content(req.book_query):
        raise HTTPException(status_code=400, detail="부적절한 입력입니다.")

    book = db.find_book(mask_pii(req.book_query))
    if not book:
        raise HTTPException(status_code=404, detail=f'"{req.book_query}"와 일치하는 책을 찾을 수 없습니다.')

    session_id = uuid.uuid4().hex
    db.create_session(
        session_id=session_id,
        user_pseudo_id=req.user_pseudo_id,
        book_id=book["book_id"],
        coaching_style=req.coaching_style,
    )

    # AI의 첫 인사 — 책에 그라운딩된 오프닝 질문
    opening, latency_ms, cost = engine.opening_message(
        style=req.coaching_style,
        book_title=book["title"],
        book_author=book["author"] or "",
        book_summary=book["summary"] or "",
    )

    # turn_index 0 = assistant의 첫 메시지
    db.insert_turn(
        session_id=session_id, turn_index=0, role="assistant",
        content=opening, thinking_stage=None,
        latency_ms=latency_ms, cost_usd=cost,
    )
    db.update_session_totals(session_id, add_cost=cost)
    _log_turn(
        timestamp=datetime.now().isoformat(),
        session_id=session_id, turn_index=0, role="assistant",
        coaching_style=req.coaching_style, thinking_stage=None,
        latency_ms=latency_ms, cost_usd=round(cost, 8),
        memory_compacted=False, status="ok",
    )

    return StartSessionResponse(
        session_id=session_id,
        book_id=book["book_id"],
        book_title=book["title"],
        book_author=book["author"] or "",
        coaching_style=req.coaching_style,
        opening_message=opening,
    )


# ──────────────────────────────────────────────────────
# 2) 한 턴 진행
# ──────────────────────────────────────────────────────
@app.post("/session/turn", response_model=TurnResponse)
def take_turn(req: TurnRequest):
    sess = db.get_session(req.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    if sess["ended_at"] is not None:
        raise HTTPException(status_code=400, detail="이미 종료된 세션입니다.")

    # ── 안전 게이트 ──
    if check_unsafe_content(req.user_message):
        raise HTTPException(status_code=400, detail="부적절한 입력입니다.")
    masked, short_circuit, override = safety_gate(req.user_message)

    # 사용자 턴 저장 (마스킹된 본문)
    user_idx = db.next_turn_index(req.session_id)
    db.insert_turn(
        session_id=req.session_id, turn_index=user_idx, role="user",
        content=masked, thinking_stage=None, latency_ms=None, cost_usd=None,
    )

    # 위기 분기 — LLM 호출 없이 안전 응답
    if short_circuit:
        ai_idx = user_idx + 1
        db.insert_turn(
            session_id=req.session_id, turn_index=ai_idx, role="assistant",
            content=override, thinking_stage="crisis",
            latency_ms=0, cost_usd=0.0,
        )
        _log_turn(
            timestamp=datetime.now().isoformat(),
            session_id=req.session_id, turn_index=ai_idx, role="assistant",
            coaching_style=sess["coaching_style"], thinking_stage="crisis",
            latency_ms=0, cost_usd=0.0, memory_compacted=False, status="crisis_redirect",
        )
        return TurnResponse(
            session_id=req.session_id, turn_index=ai_idx,
            assistant_message=override, thinking_stage="crisis",
            latency_ms=0, cost_usd=0.0, memory_compacted=False,
        )

    # ── 정상 경로: 메모리 압축 → LLM 호출 ──
    all_turns = db.list_turns(req.session_id)
    # all_turns에는 방금 넣은 사용자 메시지도 포함됨 → 컨텍스트에서는 빼고 별도 전달
    history = [t for t in all_turns if not (t["turn_index"] == user_idx and t["role"] == "user")]

    context_messages, compacted = build_context_messages(
        all_turns=history,
        recent_keep_turns=MEM_RECENT_KEEP,
        trigger_compaction_at=MEM_TRIGGER_AT,
        summarizer=engine.summarize_old_turns,
    )

    assistant_text, stage, latency_ms, cost = engine.generate_turn(
        style=sess["coaching_style"],
        book_title=sess["book_title"],
        book_author=sess["book_author"] or "",
        book_summary=sess["book_summary"] or "",
        context_messages=context_messages,
        user_message=masked,
    )

    ai_idx = user_idx + 1
    db.insert_turn(
        session_id=req.session_id, turn_index=ai_idx, role="assistant",
        content=assistant_text, thinking_stage=stage,
        latency_ms=latency_ms, cost_usd=cost,
    )
    db.update_session_totals(req.session_id, add_cost=cost)

    _log_turn(
        timestamp=datetime.now().isoformat(),
        session_id=req.session_id, turn_index=ai_idx, role="assistant",
        coaching_style=sess["coaching_style"], thinking_stage=stage,
        latency_ms=latency_ms, cost_usd=round(cost, 8),
        memory_compacted=compacted, status="ok",
    )

    return TurnResponse(
        session_id=req.session_id, turn_index=ai_idx,
        assistant_message=assistant_text, thinking_stage=stage,
        latency_ms=latency_ms, cost_usd=cost, memory_compacted=compacted,
    )


# ──────────────────────────────────────────────────────
# 3) 세션 종료 + 회고문
# ──────────────────────────────────────────────────────
@app.post("/session/end", response_model=EndSessionResponse)
def end_session(req: EndSessionRequest):
    sess = db.get_session(req.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    all_turns = db.list_turns(req.session_id)
    if len(all_turns) < 2:
        raise HTTPException(status_code=400, detail="대화가 충분하지 않아 회고문을 생성할 수 없습니다.")

    full_dialogue = render_full_dialogue(all_turns)
    data, cost = engine.generate_reflection(
        book_title=sess["book_title"],
        book_author=sess["book_author"] or "",
        full_dialogue=full_dialogue,
    )

    db.save_reflection(
        session_id=req.session_id,
        themes=data["themes"],
        open_questions=data["open_questions"],
        summary_text=data["summary_text"],
    )
    db.update_session_totals(req.session_id, add_cost=cost, ended=True)

    sess_after = db.get_session(req.session_id)
    return EndSessionResponse(
        session_id=req.session_id,
        total_turns=sess_after["total_turns"],
        total_cost_usd=float(sess_after["total_cost_usd"]),
        reflection=Reflection(
            themes=data["themes"],
            open_questions=data["open_questions"],
            summary_text=data["summary_text"],
        ),
    )


# ──────────────────────────────────────────────────────
# Ops 조회
# ──────────────────────────────────────────────────────
@app.get("/ops/sessions")
def ops_sessions(limit: int = 30):
    return db.list_sessions_recent(limit=limit)


@app.get("/ops/styles")
def ops_styles():
    return db.style_aggregate_stats()


# ──────────────────────────────────────────────────────
# 운영 종합 메트릭 — 비용·지연·안전·품질을 한 화면에
#   (피드백 4: 최종 산출물을 대시보드/노트북 중심으로)
#   logs/turns.csv(운영 로그) + eval_summary.json(평가 노트북 산출)을 합산.
# ──────────────────────────────────────────────────────
EVAL_SUMMARY_PATH = "notebooks/eval_summary.json"


@app.get("/ops/overview")
def ops_overview():
    out = {
        "performance": None,   # 지연
        "cost": None,          # 비용
        "safety": None,        # 안전 분기
        "quality": None,       # 평가 노트북 품질 점수(있으면)
    }

    # ── 비용·지연·안전: 운영 로그에서 집계 ──
    if os.path.exists(LOG_PATH):
        try:
            df = pd.read_csv(LOG_PATH)
        except Exception:
            df = pd.DataFrame()
        if not df.empty:
            ai = df[df["role"] == "assistant"]
            ok = ai[ai["status"] == "ok"]
            lat = pd.to_numeric(ok["latency_ms"], errors="coerce").dropna()
            cost = pd.to_numeric(ai["cost_usd"], errors="coerce").dropna()
            out["performance"] = {
                "n_assistant_turns": int(len(ai)),
                "latency_p50_ms": float(lat.quantile(0.50)) if len(lat) else None,
                "latency_p95_ms": float(lat.quantile(0.95)) if len(lat) else None,
                "latency_p95_target_ms": 5000,
            }
            out["cost"] = {
                "total_cost_usd": round(float(cost.sum()), 6),
                "avg_cost_per_turn_usd": round(float(cost.mean()), 8) if len(cost) else None,
            }
            status_counts = df["status"].value_counts().to_dict()
            out["safety"] = {
                "crisis_redirects": int(status_counts.get("crisis_redirect", 0)),
                "ok_turns": int(status_counts.get("ok", 0)),
                # crisis 분기는 LLM 호출 없이 안전 응답 → 0건 누락이 곧 위험.
                "crisis_redirect_rate": round(
                    status_counts.get("crisis_redirect", 0) / max(len(ai), 1), 4
                ),
            }

    # ── 품질: 평가 노트북이 남긴 요약(있을 때만) ──
    if os.path.exists(EVAL_SUMMARY_PATH):
        try:
            with open(EVAL_SUMMARY_PATH, "r", encoding="utf-8") as f:
                out["quality"] = json.load(f)
        except Exception:
            out["quality"] = None

    return out
