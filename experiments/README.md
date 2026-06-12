# 실험 관리 (Experiment Tracking)

본 과제는 **모델 학습이 없으므로(No-Training)**, AutoML(하이퍼파라미터 탐색) 대신
**모델 × 프롬프트 조합을 체계적으로 탐색·비교**하는 것이 LLM 서비스의 '실험 관리'다.

## MLflow

`notebooks/02_model_experiment_mlflow.ipynb`가 각 생성 모델(gpt-4o-mini / gpt-4o)을
하나의 run으로 기록한다.

- **params:** model, judge_model, mode(live/offline), n_golden, styles
- **metrics:** depth_overall, depth_v1/v2/v3, fabrication_rate, avg_cost_usd, avg_latency_ms
- **저장 위치:** 프로젝트 루트 `./mlruns` (파일 스토어, `.gitignore` 처리)

```bash
# 실험 UI 띄우기
mlflow ui --backend-store-uri ./mlruns      # http://localhost:5000
```

미설치 환경에서는 `experiments/runs.csv`로 자동 폴백되어 동일 지표가 누적 기록된다.

## 산출물(요약 JSON, Git에 커밋되는 증빙)

| 파일 | 의미 |
|------|------|
| `notebooks/model_comparison.json` | 품질 최고안 vs 비용효율 최고안 결정 |
| `notebooks/eval_summary.json` | 03 평가+사람보정(Spearman) 요약 (대시보드가 소비) |
| `notebooks/xai_summary.json` | 04 XAI 핵심 동인 |

## 회귀 게이트

프롬프트(`configs/prompts.yaml`)나 모델을 바꾸면 02→03 노트북을 재실행해
Depth 하락·환각률 상승이 없는지 확인하고, 새 run을 MLflow에 남긴 뒤
`*.json` 산출물과 데이터 버전(.dvc)을 함께 커밋한다. → 코드·데이터·실험의 3중 재현성.
