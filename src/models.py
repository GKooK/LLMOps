"""
API 요청/응답 스키마.

세션 단위로 엔드포인트가 분리됨 (/session/start, /session/turn, /session/end).
응답에 thinking_stage(Function Call 결과)와 turn_index가 포함된다.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal


# ────────── 세션 시작 ──────────
class StartSessionRequest(BaseModel):
    user_pseudo_id: str = Field(..., description="익명 사용자 식별자")
    book_query: str = Field(..., description="제목/저자 중 하나 (DB에서 찾아 그라운딩)")
    coaching_style: Literal["v1", "v2", "v3"] = Field(
        default="v2",
        description="v1=Neutral, v2=Inquiry, v3=Challenger"
    )


class StartSessionResponse(BaseModel):
    session_id: str
    book_id: int
    book_title: str
    book_author: str
    coaching_style: str
    opening_message: str  # AI의 첫 인사 + 첫 질문


# ────────── 1턴 진행 ──────────
class TurnRequest(BaseModel):
    session_id: str
    user_message: str


class TurnResponse(BaseModel):
    session_id: str
    turn_index: int            # 이 응답이 세션 내 몇 번째 턴인지
    assistant_message: str
    thinking_stage: Optional[str] = None  # Function Call로 분류된 사용자 발화의 사고 단계
    latency_ms: int
    cost_usd: float
    memory_compacted: bool      # 이번 턴에 메모리 압축이 일어났는지(관찰성)


# ────────── 세션 종료 + 회고문 ──────────
class EndSessionRequest(BaseModel):
    session_id: str


class Reflection(BaseModel):
    themes: List[str]
    open_questions: List[str]
    summary_text: str


class EndSessionResponse(BaseModel):
    session_id: str
    total_turns: int
    total_cost_usd: float
    reflection: Reflection


# ────────── 운영 패널 조회 ──────────
class SessionSummary(BaseModel):
    session_id: str
    book_title: str
    coaching_style: str
    total_turns: int
    total_cost_usd: float
    started_at: str
    ended_at: Optional[str] = None
