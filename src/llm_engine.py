"""
LLM 엔진.

핵심 책임:
  1) 멀티턴 대화 컨텍스트 구성 후 답변 생성.
  2) Function Calling을 함께 사용해 "사용자 발화의 사고 단계"를
     동일 호출 안에서 분류한다 (별도 호출 추가 없음 → 비용 효율적).
  3) 오래된 대화는 메모리 매니저를 통해 압축하여 토큰을 절감한다.
"""
import os
import json
import time
import yaml
from typing import List, Dict, Tuple, Optional
from openai import OpenAI


# ───────── Function Calling 스키마 ─────────
# Bloom's taxonomy를 단순화한 4단계로 사용자 발화를 분류
THINKING_STAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_user_thinking_stage",
        "description": (
            "사용자의 직전 발화가 어느 사고 단계에 해당하는지 분류한다. "
            "이 정보는 화면 표시용 메타로만 사용되며, 답변 자체에는 직접 포함되지 않는다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": ["observation", "interpretation", "evaluation", "application"],
                    "description": (
                        "observation=책 내용 묘사/사실 진술, "
                        "interpretation=의미 해석/감상, "
                        "evaluation=비판·동의·반대, "
                        "application=내 삶/현실로 연결"
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": "이 분류를 택한 한 문장 근거 (한국어)",
                },
            },
            "required": ["stage", "rationale"],
        },
    },
}


class LLMEngine:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        with open("configs/model.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.model_name = cfg["openai"]["model_name"]
        self.temperature = cfg["openai"]["temperature"]
        self.max_tokens = cfg["openai"]["max_tokens"]
        self.input_per_million = cfg["pricing"]["input_per_million"]
        self.output_per_million = cfg["pricing"]["output_per_million"]

        with open("configs/prompts.yaml", "r", encoding="utf-8") as f:
            self.prompts = yaml.safe_load(f)

    # ──────────────────────────────────────────────────────
    # 비용 계산
    # ──────────────────────────────────────────────────────
    def _calc_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens / 1_000_000 * self.input_per_million
            + completion_tokens / 1_000_000 * self.output_per_million
        )

    # ──────────────────────────────────────────────────────
    # 1) 세션 첫 인사 메시지 생성
    # ──────────────────────────────────────────────────────
    def opening_message(self, style: str, book_title: str, book_author: str, book_summary: str) -> Tuple[str, int, float]:
        sys_prompt = self.prompts["system"][style].format(
            book_title=book_title,
            book_author=book_author,
            book_summary=book_summary or "(요약 없음)",
        )
        user_seed = (
            f'이 사용자는 방금 "{book_title}"({book_author})에 대해 이야기를 나누고 싶다고 했습니다. '
            f'반갑게 인사하고, 이 책으로 토론을 시작할 수 있도록 책의 한 장면이나 핵심 질문 하나를 던지세요. '
            f'2~3문장.'
        )

        t0 = time.time()
        resp = self.client.chat.completions.create(
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_seed},
            ],
        )
        latency_ms = int((time.time() - t0) * 1000)
        text = resp.choices[0].message.content or ""
        cost = self._calc_cost(resp.usage.prompt_tokens, resp.usage.completion_tokens)
        return text.strip(), latency_ms, cost

    # ──────────────────────────────────────────────────────
    # 2) 일반 턴 — 메모리 매니저가 만든 context_messages를 받아 답변
    #    + Function Call로 사용자 발화의 사고 단계 분류를 동시 수행
    # ──────────────────────────────────────────────────────
    def generate_turn(
        self,
        style: str,
        book_title: str,
        book_author: str,
        book_summary: str,
        context_messages: List[Dict],
        user_message: str,
    ) -> Tuple[str, Optional[str], int, float]:
        """
        Returns:
            assistant_text, thinking_stage (or None), latency_ms, cost_usd
        """
        sys_prompt = self.prompts["system"][style].format(
            book_title=book_title,
            book_author=book_author,
            book_summary=book_summary or "(요약 없음)",
        )

        # 시스템 + 압축 컨텍스트 + 현재 사용자 메시지
        messages = (
            [{"role": "system", "content": sys_prompt}]
            + context_messages
            + [{"role": "user", "content": user_message}]
        )

        t0 = time.time()
        # tool_choice는 "auto"로 두어, 모델이 분류 도구를 자율적으로 호출하게 함
        resp = self.client.chat.completions.create(
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            messages=messages,
            tools=[THINKING_STAGE_TOOL],
            tool_choice="auto",
        )
        latency_ms = int((time.time() - t0) * 1000)

        msg = resp.choices[0].message
        text = (msg.content or "").strip()

        # tool_call 결과 파싱 (있을 수도 없을 수도)
        stage = None
        if msg.tool_calls:
            try:
                args = json.loads(msg.tool_calls[0].function.arguments or "{}")
                stage = args.get("stage")
            except Exception:
                stage = None

        # tool 호출만 하고 답변 텍스트가 비어있는 경우 → 2차 호출로 답변 마무리
        if not text and msg.tool_calls:
            messages.append(msg.model_dump(exclude_none=True))
            messages.append({
                "role": "tool",
                "tool_call_id": msg.tool_calls[0].id,
                "content": json.dumps({"ok": True}),
            })
            t1 = time.time()
            resp2 = self.client.chat.completions.create(
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=messages,
            )
            text = (resp2.choices[0].message.content or "").strip()
            latency_ms += int((time.time() - t1) * 1000)
            cost = self._calc_cost(
                resp.usage.prompt_tokens + resp2.usage.prompt_tokens,
                resp.usage.completion_tokens + resp2.usage.completion_tokens,
            )
        else:
            cost = self._calc_cost(resp.usage.prompt_tokens, resp.usage.completion_tokens)

        return text, stage, latency_ms, cost

    # ──────────────────────────────────────────────────────
    # 3) 메모리 압축용 요약기 — memory.py에서 주입받는 콜러블
    # ──────────────────────────────────────────────────────
    def summarize_old_turns(self, old_turns: List[Dict]) -> str:
        """오래된 턴들을 1개의 짧은 한국어 요약 문단으로 압축."""
        dialog = "\n".join(
            f'[{("사용자" if t["role"]=="user" else "코치")}] {t["content"]}' for t in old_turns
        )
        prompt = (
            "다음은 한 독서 토론 세션의 앞부분 대화입니다. "
            "이후 대화에서 코치가 일관성을 유지할 수 있도록, 사용자가 어떤 입장·감상·질문을 표명했는지를 "
            "5~7문장 이내의 한국어 요약문으로 정리하세요. 군더더기 없이.\n\n" + dialog
        )
        resp = self.client.chat.completions.create(
            model=self.model_name,
            temperature=0.2,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.choices[0].message.content or "").strip()

    # ──────────────────────────────────────────────────────
    # 4) 회고문 생성 — JSON 강제
    # ──────────────────────────────────────────────────────
    def generate_reflection(
        self, book_title: str, book_author: str, full_dialogue: str
    ) -> Tuple[Dict, float]:
        prompt = self.prompts["reflection"].format(
            book_title=book_title,
            book_author=book_author,
            full_dialogue=full_dialogue,
        )
        resp = self.client.chat.completions.create(
            model=self.model_name,
            temperature=0.3,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or "{}"
        cost = self._calc_cost(resp.usage.prompt_tokens, resp.usage.completion_tokens)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {"themes": [], "open_questions": [], "summary_text": text}
        # 누락 필드 안전 기본값
        data.setdefault("themes", [])
        data.setdefault("open_questions", [])
        data.setdefault("summary_text", "")
        return data, cost
