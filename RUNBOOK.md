# 🛠 실행 가이드 (RUNBOOK)

이 문서는 **독서 토론 코칭 시스템(Reading Coach)** 을 처음부터 실행·시연하는 방법을 정리한다.
실제 배포 중 마주친 이슈와 해결책까지 포함한다(2026-06 라이브 검증 기준).

- 경로 A — **전체 Docker 라이브 시연** (실제 대화까지) … OpenAI 키 + 결제 + Docker 필요
- 경로 B — **오프라인 노트북 시연** (LLMOps 평가/실험/XAI) … 키·Docker 불필요
- 부록 — Git/GitHub, DVC, MLflow, 정지/정리, 트러블슈팅

---

## 0. 사전 준비물

| 항목 | 경로 A(앱) | 경로 B(노트북) |
|------|:---:|:---:|
| Docker Desktop | 필요 | — |
| OpenAI API 키 + **결제(크레딧)** | 필요 | 선택(있으면 라이브) |
| Python 3.11 | — | 필요 |

> 🔑 **OpenAI 키는 결제(크레딧)가 활성화되어 있어야 한다.** 키가 유효해도 크레딧이 없으면
> `429 insufficient_quota`가 발생한다(아래 트러블슈팅 참고). gpt-4o-mini는 턴당 약 $0.0001~0.0002로 매우 저렴하다.

---

## 경로 A — 전체 Docker 라이브 시연

### A-1. Docker Desktop 실행
시작 메뉴 → **Docker Desktop** 실행 → 우하단 고래 아이콘이 초록 "Running"이 될 때까지 대기.

확인:
```bash
docker ps        # 에러 없이 표가 나오면 데몬 가동 중
```

### A-2. 환경변수(.env) 설정
```bash
cp .env.example .env       # 최초 1회
# .env 를 열어 OPENAI_API_KEY=sk-... 를 실제 키로 교체 (DB 설정은 그대로 두기)
```
> `.env`는 `.gitignore`에 포함되어 커밋되지 않는다. **키를 채팅·코드·커밋에 노출하지 말 것.**

### A-3. 빌드 & 기동
```bash
docker compose up --build -d     # 첫 빌드는 수 분 소요
docker compose ps                # db(healthy) · backend · frontend 모두 Up 확인
```
- 부팅 순서: DB(healthcheck 통과) → backend → frontend
- 첫 부팅 시 정제본 `data/books_clean.csv`(없으면 원천 `books.csv`를 견고 파서로) **18권 자동 적재**

> `.env`를 **나중에** 바꿨다면 백엔드가 옛 값을 들고 있으므로 재기동:
> ```bash
> docker compose up -d            # 변경된 env로 backend 컨테이너 재생성
> ```

### A-4. 헬스체크
```bash
curl http://localhost:8000/health           # {"status":"ok"}
curl http://localhost:8000/ops/overview      # 비용·지연·안전·품질 종합
```

### A-5. 접속 & 시연 클릭 순서
- **사용자 UI:** http://localhost:8501
- **API 문서:** http://localhost:8000/docs

1. 책 `데미안` 입력 → 사이드바 코칭 스타일 `v2` 선택 → AI 첫 질문
2. `"새는 알을 깨고 나온다"는 구절이 인상 깊었어요` 입력
   → 코치가 **사용자 말에 닻 내린 열린 질문** + 직전 응답 **지연·비용** 메트릭 표시
3. 한두 턴 더 진행(대화가 길어지면 **메모리 압축🔻** 표시)
4. `죽고 싶다`류 입력 → **위기 안내(1393) 분기**(LLM 미호출, cost=0)
5. **"이 세션을 마치고 회고문 받기"** → themes / open_questions / summary 자동 생성
6. 사이드바 **운영 종합** 패널에서 비용·지연(p95)·안전(위기분기)·품질(평가 점수) 한 화면

### A-6. 라이브 동작 검증(스크립트)
대화를 코드로 한 번에 확인하려면(인코딩 안전하게 Python `requests` 사용):
```bash
python - <<'PY'
import requests
B='http://localhost:8000'
d=requests.post(B+'/session/start',json={'user_pseudo_id':'t','book_query':'데미안','coaching_style':'v2'}).json()
sid=d['session_id']; print('opening:', d['opening_message'][:80])
d=requests.post(B+'/session/turn',json={'session_id':sid,'user_message':'익숙한 세계를 부수는 일 같아요.'}).json()
print('coach:', d['assistant_message'][:80], '| %dms | $%.6f'%(d['latency_ms'], d['cost_usd']))
print('overview:', requests.get(B+'/ops/overview').json()['performance'])
PY
```

---

## 경로 B — 오프라인 노트북 시연 (키·Docker 불필요)

LLMOps 평가·실험관리·모델비교·XAI 전 과정을 **비용 0**으로 재현한다.
```bash
pip install -r requirements-analysis.txt        # dvc·mlflow·sklearn·shap·jupyter 등
python -m src.data_prep                          # ④ 전처리 → books_clean.csv + 매니페스트
jupyter notebook
#  01_data_understanding.ipynb      ①④ EDA·전처리·Feature Engineering
#  02_model_experiment_mlflow.ipynb ⑤⑥ MLflow 실험추적 + 모델(gpt-4o-mini vs gpt-4o) 비교
#  03_evaluation_calibration.ipynb  ⑥  LLM-as-a-Judge + 사람보정(Spearman ≥ 0.70)
#  04_xai.ipynb                     ⑦  SHAP로 '좋은 질문' 동인 해석
mlflow ui --backend-store-uri ./mlruns           # ⑤ 실험 비교 UI (http://localhost:5000)
```
- 모든 노트북은 `OPENAI_API_KEY`가 없으면 자동으로 **오프라인 모의 모드**로 완주한다.
- 산출물(증빙): `notebooks/eval_summary.json`, `model_comparison.json`, `xai_summary.json`.

---

## 부록 1. Git / GitHub

```bash
# 원격 저장소
git remote -v                                    # origin = https://github.com/GKooK/LLMOps.git

# 변경 후 푸시
git add -A
git commit -m "메시지"
git push origin main
```

## 부록 2. DVC (데이터 버전 관리)

```bash
# clone 직후 데이터 복원 (실데이터는 Git이 아니라 DVC에 있음)
dvc pull

# 데이터가 바뀌었을 때
python -m src.data_prep
dvc add data/books_clean.csv
git add data/books_clean.csv.dvc data/data_registry.json
git commit -m "data: 정제본 갱신" && dvc push
```
> 현재 DVC remote는 로컬 폴더(`./dvcstore`)다. 다른 PC와 공유하려면 S3/GCS 등으로 교체:
> `dvc remote add -d storage s3://버킷/경로 && dvc push`

## 부록 3. 정지 / 정리

```bash
docker compose stop          # 잠시 멈춤(데이터 유지)
docker compose down          # 컨테이너·네트워크 제거(DB 볼륨은 유지)
docker compose down -v       # DB 볼륨까지 완전 삭제(초기화)
```

---

## 부록 4. 트러블슈팅 (실제 배포 중 발생 사례)

| 증상 | 원인 | 해결 |
|------|------|------|
| backend가 `TypeError: ... unexpected keyword argument 'proxies'`로 크래시루프 | `openai 1.52`가 `httpx≥0.28`(proxies 인자 제거)와 충돌 | `requirements.txt`에 `httpx==0.27.2` 핀 → `docker compose up -d --build backend` (이미 반영됨) |
| `/session/start`가 `429 insufficient_quota` | 키는 유효하나 **OpenAI 계정 크레딧 없음** | platform.openai.com → Billing에서 결제수단/크레딧 추가(최소 $5). **재시작 불필요** |
| `{"detail":"There was an error parsing the body"}` | 셸이 한글 JSON을 잘못 인코딩 | curl 대신 Python `requests` 또는 UTF-8 파일(`--data-binary @body.json`) 사용 |
| `docker ps`가 `cannot connect ... dockerDesktopLinuxEngine` | Docker Desktop 미실행 | Docker Desktop 실행 후 Running 대기 |
| `.env` 키를 바꿔도 반영 안 됨 | 컨테이너가 옛 env로 떠 있음 | `docker compose up -d`로 backend 재생성 |
| `docker-compose.yml ... 'version' is obsolete` 경고 | Compose v2에서 `version:` 키 폐기 | 무시 가능(이미 제거함) |
| 일반 턴의 `thinking_stage`가 `None` | Function Calling을 `tool_choice="auto"`로 둬 모델이 분류 도구 호출을 건너뜀 | 화면 표시용 메타라 응답 품질엔 영향 없음. 항상 표시하려면 `llm_engine.py`에서 `tool_choice` 강제(비용 약간 증가) |

---

## 부록 5. 라이브 검증 결과 (2026-06-12)

실제 Docker 기동 + OpenAI 라이브 호출로 전 기능 확인:

| 항목 | 결과 |
|------|------|
| 데이터 시드(prod) | 정제본 18권 자동 적재 ✅ |
| v2 멀티턴 코칭 | 사용자 발화에 그라운딩된 열린 질문 생성 ✅ |
| 위기 안전분기 | LLM 미호출(cost=0), 1393 안내 ✅ |
| 자동 회고문 | themes/open_questions/summary 생성 ✅ |
| 지연 | p95 ≈ 3.4s (목표 5s 이내) ✅ |
| 비용 | 세션 ≈ $0.0008 (목표 $0.005 이내) ✅ |
| 운영 종합 패널 | 비용·지연·안전·품질 집계 노출 ✅ |
