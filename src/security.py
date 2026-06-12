"""
안전 필터.

- PII (전화/이메일/주민번호) → 자동 마스킹
- 일반 유해어(폭언/혐오 등) → 차단(HTTPException)
- 자해·자살·심한 우울감 키워드 → '코칭 중단 + 전문기관 안내' 분기
  (사용자가 도움을 구할 가능성이 있는 발화에 대해
   무관심한 차단보다 안전한 응답을 제공하기 위함)
"""
import re
from typing import Tuple


# ────────── PII 패턴 ──────────
_PII_PATTERNS = [
    (re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"), "[PHONE_REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL_REDACTED]"),
    (re.compile(r"\b\d{6}-?\d{7}\b"), "[RRN_REDACTED]"),  # 한국 주민번호 형태
]


def mask_pii(text: str) -> str:
    for pat, repl in _PII_PATTERNS:
        text = pat.sub(repl, text)
    return text


# ────────── 일반 유해어 ──────────
_BLOCK_KEYWORDS = [
    "씨발", "병신", "개새끼",  # 비속어 예시
    "테러", "폭탄",            # 위협 예시
]


def check_unsafe_content(text: str) -> bool:
    """차단해야 하는 일반 유해 발화면 True."""
    low = text.lower()
    return any(k in low for k in _BLOCK_KEYWORDS)


# ────────── 위기(Crisis) 감지 ──────────
# 차단이 아니라 '코칭 중단 + 안내'로 분기되어야 하는 키워드
_CRISIS_KEYWORDS = [
    "자살", "죽고 싶", "죽고싶", "스스로 목숨", "자해",
    "더는 못 살", "더는 살기 싫",
]

CRISIS_RESPONSE_KO = (
    "지금 많이 힘드신 것 같아 잠시 책 이야기를 멈추겠습니다. "
    "혼자 견디지 않으셔도 됩니다. "
    "24시간 도움받을 수 있는 곳을 안내드려요:\n\n"
    "• 자살예방상담전화 ☎ 1393 (24시간 무료)\n"
    "• 정신건강위기상담전화 ☎ 1577-0199\n\n"
    "지금은 가까운 사람이나 위 번호에 연락해 주시는 것이 가장 우선입니다. "
    "준비되시면 언제든 다시 돌아와도 좋아요."
)


def detect_crisis(text: str) -> bool:
    return any(k in text for k in _CRISIS_KEYWORDS)


# ────────── 통합 게이트 ──────────
def safety_gate(text: str) -> Tuple[str, bool, str]:
    """
    Returns:
        (masked_text, should_short_circuit, override_response_or_empty)
        - should_short_circuit=True 이면 LLM 호출하지 말고 override_response를 그대로 사용자에게 보여야 함
        - check_unsafe_content가 잡히면 호출자가 HTTPException을 발생시킬 것
    """
    if detect_crisis(text):
        return mask_pii(text), True, CRISIS_RESPONSE_KO
    return mask_pii(text), False, ""
