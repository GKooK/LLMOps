"""
데이터 전처리 · Feature Engineering · 경량 데이터 버전 관리.

이 모듈은 두 종류의 데이터를 다룬다.
  1) books 메타데이터(data/books.csv) — 정제·중복 제거·피처 생성 → books_clean.csv
  2) 코치 응답(turns) — '질문 품질'을 설명하기 위한 수치 피처 추출
     (실험 비교/02 노트북, XAI/04 노트북에서 공통 사용)

DVC가 '파일 단위' 버전 관리를 담당하고, 여기의 sha256 매니페스트는
'어떤 버전이 무엇이었는지'를 사람이 읽을 수 있게 보조 기록한다(2중 안전).
"""
from __future__ import annotations
import os
import re
import json
import hashlib
from typing import Dict, List, Optional

import pandas as pd


# ════════════════════════════════════════════════════════════
# 1) books 메타데이터 전처리
# ════════════════════════════════════════════════════════════
_NONFICTION_HINTS = [
    "과학", "역사", "심리", "철학", "인류", "문명", "정보", "네트워크",
    "교양", "분석", "추적", "전망", "경제", "사회",
]


def normalize_title(title: str) -> str:
    """제목 정규화: 공백 제거·소문자화로 '총 균 쇠'와 '총균쇠'를 같은 키로."""
    return re.sub(r"\s+", "", str(title)).strip().lower()


def normalize_author(author: Optional[str]) -> Optional[str]:
    """저자 정규화: 흔한 표기 흔들림(가운뎃점/공백) 정리."""
    if author is None or (isinstance(author, float) and pd.isna(author)):
        return None
    a = re.sub(r"\s+", " ", str(author)).strip()
    # 알려진 오탈자/표기 보정
    fixes = {"무라카키 하루키": "무라카미 하루키"}
    return fixes.get(a, a)


def _sentence_count(text: str) -> int:
    if not text:
        return 0
    return len([s for s in re.split(r"[.!?。…]+", str(text)) if s.strip()])


def add_book_features(df: pd.DataFrame) -> pd.DataFrame:
    """books 메타데이터에 파생 피처 추가."""
    df = df.copy()
    df["title_norm"] = df["title"].map(normalize_title)
    df["author"] = df["author"].map(normalize_author)
    df["summary"] = df["summary"].fillna("").astype(str).str.strip()
    df["summary_char_len"] = df["summary"].str.len()
    df["summary_word_len"] = df["summary"].str.split().map(len)
    df["summary_sentence_len"] = df["summary"].map(_sentence_count)
    df["has_image"] = df["image_url"].notna() & (df["image_url"].astype(str).str.len() > 0)
    df["is_likely_nonfiction"] = df["summary"].map(
        lambda s: int(any(h in s for h in _NONFICTION_HINTS))
    )
    return df


def clean_books(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    원천 books.csv → 정제본.
      - 제목 정규화 후 중복 제거(가장 낮은 rank=대표 1건만 유지)
      - 저자 정규화, 결측 요약 처리, 파생 피처 생성
    """
    df = add_book_features(df_raw)
    before = len(df)
    df = (
        df.sort_values("rank", na_position="last")
        .drop_duplicates(subset=["title_norm"], keep="first")
        .reset_index(drop=True)
    )
    removed = before - len(df)
    if removed:
        print(f"[clean_books] 중복 {removed}건 제거 ({before} → {len(df)})")
    # 대표 컬럼 순서 정리
    cols = [
        "rank", "title", "author", "summary",
        "summary_char_len", "summary_word_len", "summary_sentence_len",
        "is_likely_nonfiction", "has_image", "yes24_url", "image_url", "title_norm",
    ]
    cols = [c for c in cols if c in df.columns]
    return df[cols]


def read_books_robust(in_path: str = "data/books.csv") -> pd.DataFrame:
    """
    원천 books.csv를 견고하게 로드.
    원천 파일에는 summary 안의 콤마가 인용부호로 감싸지지 않은 행이 있어
    표준 CSV 파서가 깨진다(데이터 품질 결함). summary가 마지막 6번째 필드이므로
    줄을 앞 5개 + 나머지(=summary)로 분해해 전체 내용을 보존한다.
    """
    rows = []
    with open(in_path, encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split(",")
        ncol = len(header)  # 6
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split(",", ncol - 1)  # maxsplit → 마지막 필드에 콤마 잔류 허용
            if len(parts) < ncol:
                parts += [""] * (ncol - len(parts))
            rows.append(parts)
    df = pd.DataFrame(rows, columns=header)
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    return df


def run_books_pipeline(in_path: str = "data/books.csv",
                       out_path: str = "data/books_clean.csv") -> pd.DataFrame:
    """books 전처리 파이프라인 실행 후 정제본 저장."""
    raw = read_books_robust(in_path)
    clean = clean_books(raw)
    clean.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[run_books_pipeline] 저장: {out_path}  (rows={len(clean)})")
    return clean


# ════════════════════════════════════════════════════════════
# 2) 코치 응답 피처 추출 (질문 품질의 '설명변수')
#    02 실험·04 XAI 노트북에서 동일하게 호출 → 일관성 보장
# ════════════════════════════════════════════════════════════
_SECOND_PERSON = ["당신", "방금", "말씀", "하셨", "라고 하", "라고 말"]


def _tokens(text: str) -> set:
    return set(t for t in re.split(r"[^0-9A-Za-z가-힣]+", str(text)) if len(t) >= 2)


def featurize_response(user_msg: str, assistant_msg: str) -> Dict[str, float]:
    """
    코치 응답 1건을 수치 피처로. (그라운딩/열림/구체성의 대리 지표)
      - resp_word_len           : 응답 단어 수
      - n_question_marks        : 물음표 개수 (질문성)
      - ends_with_question      : 물음표로 끝나는가 (열린 질문 경향)
      - user_overlap            : 사용자 발화와 토큰 Jaccard (사용자에 그라운딩)
      - second_person_refs      : '방금/당신/말씀…' 등 사용자 지시 표현 수
      - has_quote_mark          : 인용부호 포함 여부 (지어낸 인용 위험 신호로도 사용)
    """
    a = str(assistant_msg or "")
    u = str(user_msg or "")
    aw = a.split()
    ut, at = _tokens(u), _tokens(a)
    overlap = (len(ut & at) / len(ut | at)) if (ut | at) else 0.0
    return {
        "resp_word_len": float(len(aw)),
        "n_question_marks": float(a.count("?") + a.count("？")),
        "ends_with_question": float(a.rstrip().endswith(("?", "？"))),
        "user_overlap": round(overlap, 4),
        "second_person_refs": float(sum(a.count(k) for k in _SECOND_PERSON)),
        "has_quote_mark": float(any(q in a for q in ['"', "'", "“", "”", "‘", "’"])),
    }


def featurize_frame(df: pd.DataFrame,
                    user_col: str = "user_msg",
                    resp_col: str = "assistant_msg") -> pd.DataFrame:
    """응답 DataFrame 전체에 featurize_response 적용 → 피처 컬럼 추가."""
    feats = df.apply(
        lambda r: featurize_response(r[user_col], r[resp_col]), axis=1, result_type="expand"
    )
    return pd.concat([df.reset_index(drop=True), feats.reset_index(drop=True)], axis=1)


# ════════════════════════════════════════════════════════════
# 3) 경량 데이터 버전 매니페스트 (DVC 보조)
# ════════════════════════════════════════════════════════════
def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(paths: List[str], version: str,
                   manifest_path: str = "data/data_registry.json",
                   note: str = "") -> Dict:
    """추적 대상 파일들의 sha256·크기를 사람이 읽을 매니페스트로 기록."""
    entries = []
    for p in paths:
        if os.path.exists(p):
            entries.append({"path": p, "sha256": sha256_of(p),
                            "bytes": os.path.getsize(p)})
    registry = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            registry = json.load(f)
    registry[version] = {"note": note, "files": entries}
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
    return registry[version]


if __name__ == "__main__":
    # python -m src.data_prep  로 전처리 파이프라인 단독 실행
    run_books_pipeline()
    write_manifest(
        ["data/books.csv", "data/books_clean.csv", "data/golden_set.json"],
        version="v1.0", note="초기 정제본 + 골든셋",
    )
    print("done.")
