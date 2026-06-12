# 📚 독서 토론 코칭 시스템 (Reading Discussion Coach)

> 책을 다 읽었거나 읽는 중인 사용자와 **여러 턴의 대화**를 통해
> 사고의 결을 다듬는 AI 코치. 정답을 알려주는 것이 아니라,
> 사용자가 스스로 더 깊이 생각하도록 **좋은 질문**을 던진다.

---

## 🧠 핵심 기능

1. **3가지 코칭 스타일 프롬프트** — `configs/prompts.yaml`
   - `v1` 중립형 — 친절한 동반 독자 (대조군)
   - `v2` 질문 중심형 — 열린 질문으로 사고 확장 (**권장**)
   - `v3` 도전형 — Devil's Advocate, 정중한 반론으로 사고 단련
2. **세션 기반 멀티턴 대화** — `src/database.py`
   - 한 세션 = 하나의 책 토론. 모든 턴은 DB에 적재되어 회고·분석에 활용됨.
3. **대화 메모리 압축** — `src/memory.py`
   - 메시지 10개 이상이면, 오래된 부분을 LLM 요약 1개로 압축 → 토큰 절감
   - 최근 K턴은 원문 유지하여 직전 맥락 보존
4. **Function Calling으로 사고 단계 분류** — `src/llm_engine.py`
   - 답변 생성과 분류를 1회 호출로 동시 수행 (비용 효율적)
   - observation / interpretation / evaluation / application 4단계
5. **자동 회고문 생성** — `POST /session/end`
   - 세션 종료 시 JSON 스키마로 themes / open_questions / summary 생성
6. **Crisis Detection** — `src/security.py`
   - 자해·우울 키워드 감지 시 LLM 호출 차단 + 전문기관 안내로 안전 분기
7. **LLM-as-a-Judge 평가 + 사람 보정** — `notebooks/evaluation.ipynb`
   - 30+ 골든셋 × 3 스타일을 4축 루브릭(Openness/Groundedness/Specificity/Provocativeness)으로 채점
   - **환각 플래그(fabrication)** 로 요약·발화에 없는 장면을 지어냈는지 별도 점검
   - **Spearman 상관**으로 Judge 점수와 사람 점수의 일치를 검증(임계값 0.70 게이트)
   - API 키 없이도 **오프라인 모의 모드**로 전체 파이프라인 재현 가능
8. **운영 종합 메트릭** — `GET /ops/overview` + 대시보드
   - 비용·지연(p95)·안전(위기 분기)·품질(평가 점수)을 한 화면에 집계

> **그라운딩 범위(저작권·환각 방지):** 본 MVP는 책 **본문 전문을 RAG로 검색하지 않는다.**
> 코치가 닻을 내릴 수 있는 근거는 (1) DB의 짧은 **메타데이터 요약**, (2) **사용자가 직접 한 말** 둘뿐이며,
> 요약에 없는 장면·대사를 지어내 인용하는 것은 프롬프트의 `[그라운딩 규칙]`으로 금지된다.
> 구체성이 필요하면 코치가 단정하지 않고 사용자에게 장면을 묘사해 달라고 되묻는다.
> 정책의 단일 출처는 `configs/model.yaml`의 `grounding:` 블록.

---

## 🧪 MLOps 9대 요구사항 커버리지

본 프로젝트는 *모델 성능 비교*가 아니라 **하나의 AI 서비스를 개발·운영하는 MLOps 전 과정**을 다룬다.
(모델 **학습은 하지 않으며**, 품질 개선은 프롬프트·평가·실험관리·로깅으로 한다 — No-Training.)

| # | 요구사항 | 구현 산출물 |
|---|----------|-------------|
| ① | 문제 정의 및 데이터 이해 | 보고서 v0.3 + `notebooks/01_data_understanding.ipynb` (EDA) |
| ② | Source Code Version Control | **Git** 저장소 + `.gitignore` + 의미 단위 커밋 이력 |
| ③ | Data Version Control | **DVC** (`data/*.dvc`, 로컬 remote) + `data/README.md` + sha256 매니페스트 |
| ④ | 데이터 전처리 / Feature Engineering | `src/data_prep.py` (중복제거·정규화·견고파서·응답 피처) → `books_clean.csv` |
| ⑤ | AutoML / 실험 관리 | **MLflow** (`02_*.ipynb`, `./mlruns`) — 모델×프롬프트 조합 탐색·추적 |
| ⑥ | 모델 평가 및 성능 비교 | `02`(gpt-4o-mini vs gpt-4o) + `03`(4축 LLM-Judge + 사람보정 Spearman) |
| ⑦ | XAI | `04_xai.ipynb` — 대리모델 + **SHAP**/계수/순열중요도로 '좋은 질문' 동인 해석 |
| ⑧ | AI Endpoint / API 배포 | **FastAPI** (`/session/*`, `/ops/*`, Swagger) + **Docker Compose** |
| ⑨ | Web UI | **Streamlit** 채팅 + 운영 종합 대시보드 |

> 전체 파이프라인 재현 순서는 아래 [실행 방법 §5](#5-mlops-파이프라인-노트북-실행-순서) 참고.

---

## 📂 디렉토리 구조

```
reading_coach/
├── README.md
├── requirements.txt            # 앱 런타임 의존성
├── requirements-analysis.txt   # 노트북/MLOps 스택(dvc·mlflow·sklearn·shap)
├── docker-compose.yml
├── .env.example
├── .gitignore                  # ① Git 버전 관리
├── .dvc/ · data/*.dvc          # ③ DVC 데이터 버전 관리 메타
├── Dockerfile.backend / Dockerfile.frontend
├── book_db/
│   ├── init.sql          # 4 tables: books / sessions / turns / reflections
│   └── Dockerfile
├── configs/
│   ├── prompts.yaml      # 3 coaching styles + [그라운딩 규칙] + reflection
│   └── model.yaml        # 모델·비용·메모리·judge·grounding 설정
├── data/
│   ├── README.md         # ③ DVC 사용법
│   ├── books.csv         # 원천 메타데이터(DVC 추적)
│   ├── books_clean.csv   # ④ 전처리 정제본(DVC 추적)
│   ├── golden_set.json   # 평가 골든셋 30케이스(DVC 추적)
│   └── data_registry.json# sha256 데이터 매니페스트
├── src/
│   ├── main.py           # ⑧ FastAPI: 세션 + Ops(overview/styles)
│   ├── models.py         # Pydantic 스키마
│   ├── database.py       # PostgreSQL CRUD (4 tables)
│   ├── data_prep.py      # ④ 전처리·Feature Engineering·매니페스트
│   ├── llm_engine.py     # LLM + Function Calling
│   ├── memory.py         # 대화 메모리 압축
│   ├── security.py       # PII + Crisis Detection
│   └── dashboard.py      # ⑨ Streamlit (사용자 + 운영 종합 패널)
├── notebooks/
│   ├── 01_data_understanding.ipynb     # ①④ EDA·전처리·FE
│   ├── 02_model_experiment_mlflow.ipynb# ⑤⑥ 실험추적·모델비교
│   ├── 03_evaluation_calibration.ipynb # ⑥ LLM-as-a-Judge + 사람보정
│   ├── 04_xai.ipynb                    # ⑦ XAI(SHAP)
│   └── *_summary.json                  # 노트북 산출물(대시보드/증빙)
├── experiments/
│   └── README.md         # ⑤ MLflow 실험 관리
└── logs/                 # 자동 생성됨 (turns.csv)
```

---

## 🚀 실행 방법

### 1. 환경 변수
```bash
cp .env.example .env
# .env 파일을 열어 OPENAI_API_KEY 를 채워 주세요
```

### 2. 도커 실행
```bash
docker compose up --build -d
```

- DB가 healthcheck 통과 후 backend → frontend 순으로 부팅
- 첫 부팅 시 정제본 `data/books_clean.csv`(없으면 원천 `books.csv`를 견고 파서로)가 자동 적재됩니다

### 3. 접속
- 사용자 UI (Streamlit): http://localhost:8501
- Backend API: http://localhost:8000/docs (Swagger)

### 4. 사용 시나리오
1. UI에서 토론할 책 입력 (예: "데미안")
2. 사이드바에서 코칭 스타일 선택 (v1/v2/v3)
3. AI가 책에 그라운딩된 첫 질문을 던짐
4. 자유롭게 대화 (3~10턴 권장)
5. **"이 세션을 마치고 회고문 받기"** 클릭 → 자동 회고문

### 5. MLOps 파이프라인 노트북 실행 순서

```bash
pip install -r requirements-analysis.txt   # dvc·mlflow·sklearn·shap·jupyter 등

# (선택) DVC로 데이터 복원 — 다른 환경에서 clone 했을 때
dvc pull

# 전처리만 단독 실행하려면
python -m src.data_prep                     # → data/books_clean.csv + 매니페스트

# 노트북을 순서대로 실행 (모두 OPENAI_API_KEY 없이 '오프라인 모의'로 완주 가능)
jupyter notebook
#  01_data_understanding.ipynb      ①④ EDA·전처리·Feature Engineering
#  02_model_experiment_mlflow.ipynb ⑤⑥ MLflow 실험추적 + 모델 비교
#  03_evaluation_calibration.ipynb  ⑥  LLM-as-a-Judge + 사람보정(Spearman)
#  04_xai.ipynb                     ⑦  SHAP로 '좋은 질문' 동인 해석

mlflow ui --backend-store-uri ./mlruns      # ⑤ 실험 비교 UI (http://localhost:5000)
```

- **라이브 모드:** `OPENAI_API_KEY`가 있으면 실제 모델로 생성·채점한다.
- **오프라인 모드:** 키가 없으면 모델별/스타일별 품질 프로파일을 반영한 모의 데이터로
  채점·상관·실험추적·XAI·시각화·산출물 저장까지 **전 파이프라인을 재현**한다(과제 검증용).
- 산출물(증빙): `eval_summary.json`(대시보드 `/ops/overview` 소비), `model_comparison.json`, `xai_summary.json`.

---

## 🔌 API 명세 요약

```
POST /session/start
  body: { user_pseudo_id, book_query, coaching_style }
  resp: { session_id, book_title, book_author, opening_message, ... }

POST /session/turn
  body: { session_id, user_message }
  resp: { assistant_message, thinking_stage, latency_ms, cost_usd, memory_compacted, ... }

POST /session/end
  body: { session_id }
  resp: { total_turns, total_cost_usd, reflection: { themes, open_questions, summary_text } }

GET  /ops/sessions    # 최근 세션 목록
GET  /ops/styles      # 코칭 스타일별 집계 (A/B 비교용)
GET  /ops/overview    # 비용·지연(p95)·안전·품질 종합 (대시보드 패널 소스)
```

---

## 📊 KPI 목표

| 영역 | 지표 | 목표 |
|------|------|------|
| 참여 | Avg Turns/Session | ≥ 6턴 |
| 품질 | Question Depth Score | ≥ 4.0 / 5.0 |
| 품질 | Fabrication Rate (환각) | ≤ 5% |
| 품질 | Judge–사람 Spearman 상관 | ≥ 0.70 |
| 품질 | Reflection Coherence | ≥ 4.0 / 5.0 |
| 성능 | p95 Turn Latency | ≤ 5.0 s |
| 비용 | Avg Session Cost | ≤ $0.005 |
| 안전 | Crisis Detection Recall | 100% |

---

## 🗺️ 로드맵 (학습 없이 — No-Training)

> 본 프로젝트는 파인튜닝/Reward Model/DPO 같은 **모델 학습을 하지 않는다.**
> 품질 개선은 전적으로 **프롬프트 버저닝 + 골든셋 평가 회귀 + 온라인 A/B + 로깅**으로 이룬다.

- **Phase 1 (4주):** 본 MVP — 멀티턴 + 3-way A/B + 회고문 + 평가/보정 노트북
- **Phase 2 (8주):** 프롬프트 레지스트리 + CI 평가 회귀 게이트(점수 하락 시 머지 차단) + 큐레이션 모티프로 그라운딩 강화
- **Phase 3 (16주):** 온라인 A/B 자동화(가드레일 메트릭) + thumbs-up/down은 **프롬프트 개선 신호**로만 사용(학습 아님)

---

## ⚠️ 안전 정책

- PII (전화번호/이메일/주민번호) → 자동 마스킹
- 자해·자살·심한 우울감 감지 시 → 코칭 즉시 중단 + 위기상담전화 안내
- 일반 비속어/위협 → HTTP 400
