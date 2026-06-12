# 데이터 & 데이터 버전 관리 (DVC)

이 디렉토리의 **데이터 파일은 Git이 아니라 [DVC](https://dvc.org)로 버전 관리**된다.
Git에는 가벼운 포인터(`*.dvc`)만 커밋되고, 실제 데이터는 DVC 캐시/remote에 저장된다.

## 추적 대상

| 파일 | 설명 | 포인터 |
|------|------|--------|
| `books.csv` | 원천 베스트셀러 메타데이터 (summary에 비인용 콤마 결함 포함) | `books.csv.dvc` |
| `books_clean.csv` | 전처리 정제본 (중복 제거·정규화·파생 피처) — `src/data_prep.py` 산출 | `books_clean.csv.dvc` |
| `golden_set.json` | 평가용 골든셋 30 케이스 (책10×시나리오3) | `golden_set.json.dvc` |
| `data_registry.json` | sha256 매니페스트 (사람이 읽는 버전 기록, DVC 보조) | Git에 직접 커밋 |

> 실제 데이터 파일은 `data/.gitignore`(DVC가 생성)로 Git에서 제외된다.

## 명령어

```bash
# 0) DVC는 requirements에 포함 — 없으면: pip install dvc

# 1) 다른 환경에서 데이터 복원 (Git clone 직후)
dvc pull                      # .dvc 포인터 → remote에서 실제 데이터 내려받기

# 2) 데이터가 바뀌었을 때 새 버전 기록
python -m src.data_prep       # books_clean.csv 재생성 + data_registry.json 갱신
dvc add data/books_clean.csv  # 변경분을 DVC가 추적 (.dvc 해시 갱신)
git add data/books_clean.csv.dvc data/data_registry.json
git commit -m "data: 정제본 v1.1"
dvc push                      # 실제 데이터를 remote로 업로드

# 3) 과거 버전으로 롤백
git checkout <commit> -- data/books_clean.csv.dvc
dvc checkout                  # .dvc 포인터에 맞는 데이터로 워킹트리 복원
```

## Remote

기본 remote는 로컬 디렉토리(`./dvcstore`)로 설정되어 있다(`.dvc/config`).
운영에서는 S3/GCS/Azure 등으로 교체한다:

```bash
dvc remote add -d storage s3://my-bucket/reading-coach
dvc push
```

## 데이터 ↔ 코드 일관성

`books_clean.csv`의 전처리 로직과 `golden_set.json`의 골든셋은
`src/data_prep.py`(전처리)와 `notebooks/01_data_understanding.ipynb`(EDA·생성)이
**단일 출처**로 관리한다. 데이터 버전(.dvc)과 코드 버전(Git)이 함께 커밋되어
"이 코드는 이 데이터 버전에서 검증됐다"는 재현성을 보장한다.
