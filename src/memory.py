"""
대화 메모리 매니저.

세션이 길어지면 토큰이 누적되어 비용·지연이 비선형으로 증가하므로,
다음 두-구간 전략을 사용한다:

  [요약(1개)] + [최근 K턴 원문]  →  LLM 컨텍스트로 전달

핵심 규칙:
  - 메시지 수가 `trigger_compaction_at`(예: 10) 이상이면 압축 트리거
  - 가장 오래된 (전체 - keep_recent×2)개 메시지를 LLM 요약 1회로 치환
  - 요약본은 시스템 메시지 형태로 컨텍스트 맨 앞에 부착
"""
from typing import List, Dict, Tuple


def build_context_messages(
    all_turns: List[Dict],
    recent_keep_turns: int,
    trigger_compaction_at: int,
    summarizer,
) -> Tuple[List[Dict], bool]:
    """
    Args:
        all_turns: DB에서 가져온 [{"role": "user"|"assistant", "content": ...}, ...]
        recent_keep_turns: 최근 K턴(=2K 메시지)은 원문 보존
        trigger_compaction_at: 이 개수 이상이면 압축
        summarizer: callable(messages) -> 요약 문자열 (LLM 호출 함수 주입)

    Returns:
        (LLM API에 보낼 messages list, compacted: bool)
    """
    if len(all_turns) < trigger_compaction_at:
        # 압축할 필요 없음 — 전체 원문 그대로
        return _to_openai_messages(all_turns), False

    # 압축 대상 = 앞부분, 보존 대상 = 뒷부분
    keep_count = recent_keep_turns * 2  # 2 = user+assistant 쌍
    old_part = all_turns[:-keep_count]
    recent_part = all_turns[-keep_count:]

    summary_text = summarizer(old_part)

    summary_message = {
        "role": "system",
        "content": (
            "[이전 대화 요약]\n"
            f"{summary_text}\n"
            "[이전 대화 요약 끝]"
        ),
    }
    messages = [summary_message] + _to_openai_messages(recent_part)
    return messages, True


def _to_openai_messages(turns: List[Dict]) -> List[Dict]:
    return [{"role": t["role"], "content": t["content"]} for t in turns]


def render_full_dialogue(all_turns: List[Dict]) -> str:
    """회고문 생성용 — 전체 대화를 사람이 읽기 좋은 형태로 직렬화"""
    lines = []
    for t in all_turns:
        prefix = "사용자" if t["role"] == "user" else "코치"
        lines.append(f"[{prefix}] {t['content']}")
    return "\n".join(lines)
