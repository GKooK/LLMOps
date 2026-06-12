"""
Streamlit 프론트엔드.
좌측 사이드바: 코칭 스타일 선택, 운영 메트릭(스타일별 비교)
중앙: 멀티턴 채팅 + 세션 종료 시 자동 회고문
"""
import os
import uuid
import requests
import streamlit as st
import pandas as pd

API_URL = os.getenv("API_URL", "http://backend:8000")

st.set_page_config(page_title="독서 토론 코칭", layout="wide", page_icon="📚")

# ────────── 헤더 ──────────
st.title("📚 독서 토론 코칭 시스템")
st.caption("AI 독서 토론 코치 — *정답이 아니라 질문을 드립니다.*")

# ────────── 세션 상태 초기화 ──────────
if "user_pseudo_id" not in st.session_state:
    st.session_state.user_pseudo_id = uuid.uuid4().hex[:8]
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "book_meta" not in st.session_state:
    st.session_state.book_meta = None
if "reflection" not in st.session_state:
    st.session_state.reflection = None
if "last_metrics" not in st.session_state:
    st.session_state.last_metrics = None


# ────────── 사이드바: Ops 패널 ──────────
with st.sidebar:
    st.header("⚙️ 설정")
    style_label = st.radio(
        "코칭 스타일 (3-way A/B)",
        options=["v2", "v1", "v3"],
        format_func=lambda v: {
            "v1": "v1 · 중립형 (대조군)",
            "v2": "v2 · 질문 중심형 (권장)",
            "v3": "v3 · 도전형",
        }[v],
        index=0,
        help="세션 시작 시점에만 적용됩니다.",
    )

    st.divider()
    st.subheader("📈 운영 종합 (비용·지연·안전·품질)")
    try:
        ov = requests.get(f"{API_URL}/ops/overview", timeout=4).json()
        perf, cost, safety, quality = (
            ov.get("performance"), ov.get("cost"), ov.get("safety"), ov.get("quality"),
        )
        if perf and perf.get("latency_p95_ms") is not None:
            p95 = perf["latency_p95_ms"] / 1000
            st.metric(
                "p95 지연", f"{p95:.2f}s",
                delta=f"목표 {perf['latency_p95_target_ms']/1000:.0f}s",
                delta_color="inverse" if p95 > 5 else "normal",
            )
        if cost and cost.get("avg_cost_per_turn_usd") is not None:
            st.metric("턴당 평균 비용", f"${cost['avg_cost_per_turn_usd']:.6f}")
        if safety:
            st.metric(
                "위기 안전 분기", f"{safety['crisis_redirects']}건",
                help="자해·위기 발화 감지 시 LLM 호출 없이 전문기관 안내로 분기된 횟수.",
            )
        if quality and quality.get("by_style"):
            st.caption("🧪 평가 노트북 Question Depth (스타일별)")
            st.dataframe(
                pd.DataFrame(quality["by_style"]), hide_index=True, use_container_width=True,
            )
        elif quality is None:
            st.caption("품질 점수: 평가 노트북 미실행 (eval_summary.json 없음)")
    except Exception:
        st.caption("운영 메트릭 조회 실패")

    st.divider()
    st.subheader("📊 스타일별 누적 통계")
    try:
        rows = requests.get(f"{API_URL}/ops/styles", timeout=4).json()
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            st.caption("아직 종료된 세션이 없습니다.")
    except Exception:
        st.caption("백엔드 미응답")

    with st.expander("최근 세션 30건"):
        try:
            rs = requests.get(f"{API_URL}/ops/sessions?limit=30", timeout=4).json()
            if rs:
                st.dataframe(pd.DataFrame(rs), hide_index=True, use_container_width=True)
            else:
                st.caption("기록 없음")
        except Exception:
            st.caption("조회 실패")


# ────────── 본문 ──────────
if st.session_state.session_id is None:
    # ── 세션 시작 화면 ──
    st.subheader("어떤 책을 함께 읽으셨나요?")
    with st.form("start_form"):
        book_query = st.text_input("책 제목 또는 저자", placeholder="예: 데미안, 한강, 1984 ...")
        submitted = st.form_submit_button("토론 시작하기 →", type="primary")

    if submitted and book_query.strip():
        try:
            with st.spinner("코치가 책장을 살피고 있어요..."):
                resp = requests.post(
                    f"{API_URL}/session/start",
                    json={
                        "user_pseudo_id": st.session_state.user_pseudo_id,
                        "book_query": book_query.strip(),
                        "coaching_style": style_label,
                    },
                    timeout=30,
                )
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.session_id = data["session_id"]
                st.session_state.book_meta = {
                    "title": data["book_title"],
                    "author": data["book_author"],
                    "style": data["coaching_style"],
                }
                st.session_state.messages = [
                    {"role": "assistant", "content": data["opening_message"]},
                ]
                st.rerun()
            else:
                st.error(f"오류: {resp.json().get('detail', '알 수 없는 오류')}")
        except Exception as e:
            st.error(f"백엔드 연결 실패: {e}")

    st.info(
        "💡 이 시스템은 책의 정답을 알려주는 추천 서비스가 아닙니다. "
        "당신이 읽은 책에 대해 **함께 사고를 정리할 수 있도록 질문을 던지는 코치**입니다."
    )

else:
    # ── 진행 중 세션 ──
    meta = st.session_state.book_meta
    style_caption = {"v1": "중립형", "v2": "질문 중심형", "v3": "도전형"}[meta["style"]]
    st.markdown(f"**📖 {meta['title']}** · {meta['author']}  ·  🎙️ *{style_caption} 코치*")

    if st.session_state.last_metrics:
        m = st.session_state.last_metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("직전 응답 지연", f"{m['latency_ms']/1000:.2f}s")
        c2.metric("직전 응답 비용", f"${m['cost_usd']:.6f}")
        c3.metric(
            "메모리 압축",
            "🔻 적용됨" if m["memory_compacted"] else "—",
            help="대화가 길어지면 오래된 턴은 1개 요약으로 압축됩니다.",
        )

    # 대화 표시
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("thinking_stage"):
                st.caption(f"🧠 직전 사용자 발화의 사고 단계: `{msg['thinking_stage']}`")

    # 입력
    if prompt := st.chat_input("이 책에서 떠오른 생각을 적어 보세요..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("코치가 듣고 있어요..."):
                try:
                    resp = requests.post(
                        f"{API_URL}/session/turn",
                        json={"session_id": st.session_state.session_id, "user_message": prompt},
                        timeout=60,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        st.markdown(data["assistant_message"])
                        if data.get("thinking_stage"):
                            st.caption(f"🧠 직전 사용자 발화의 사고 단계: `{data['thinking_stage']}`")
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": data["assistant_message"],
                            "thinking_stage": data.get("thinking_stage"),
                        })
                        st.session_state.last_metrics = data
                    else:
                        st.error(f"오류: {resp.json().get('detail','')}")
                except Exception as e:
                    st.error(f"백엔드 실패: {e}")

    st.divider()

    # 종료 버튼
    col1, col2 = st.columns([1, 1])
    if col1.button("✍️ 이 세션을 마치고 회고문 받기", type="primary"):
        with st.spinner("이번 세션을 한 권의 작은 글로 정리하고 있어요..."):
            try:
                resp = requests.post(
                    f"{API_URL}/session/end",
                    json={"session_id": st.session_state.session_id},
                    timeout=60,
                )
                if resp.status_code == 200:
                    st.session_state.reflection = resp.json()
                else:
                    st.error(f"오류: {resp.json().get('detail','')}")
            except Exception as e:
                st.error(f"실패: {e}")

    if col2.button("🔄 새 책으로 다시 시작"):
        st.session_state.session_id = None
        st.session_state.messages = []
        st.session_state.book_meta = None
        st.session_state.reflection = None
        st.session_state.last_metrics = None
        st.rerun()

    # 회고문 표시
    if st.session_state.reflection:
        r = st.session_state.reflection
        ref = r["reflection"]
        st.subheader("📝 오늘의 독서 회고")
        st.caption(f"총 턴: {r['total_turns']}  ·  세션 총 비용: ${r['total_cost_usd']:.6f}")
        st.markdown("**핵심 주제**")
        for t in ref["themes"]:
            st.markdown(f"- {t}")
        st.markdown("**아직 답하지 않은 질문**")
        for q in ref["open_questions"]:
            st.markdown(f"- {q}")
        st.markdown("**사고 여정 요약**")
        st.write(ref["summary_text"])
