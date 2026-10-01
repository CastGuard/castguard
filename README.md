# CastGuard · 전처리 데이터 전달

협업에 필요한 **원본 데이터, 전처리 결과, 처리 명세**를 제공한다.

## 시작하기

1. [전처리·데이터 사용 명세](docs/PREPROCESSING.md)를 읽는다.
2. `data/processed/`의 데이터 3개를 사용한다.
3. `feature_contract.json`으로 입력 열을 선택하고 `folds.csv`의 고정 분할로 학습·평가한다.

| 파일 | 용도 |
|---|---|
| `joined.parquet` | #42 품질 + #41 과거 이력, 4,617 Shot |
| `m41_timeline.parquet` | #41 전체 타임라인, 5,161행 |
| `d40_clean.parquet` | #40 정제 공정 데이터, 73,612행 |
| `folds.csv` | 학습·검증·시험 역할 배정 |
| `feature_contract.json` | 실험별 입력 허용목록 |
| `manifest.json` | 파일 크기·행열 수·SHA-256 및 처리 설정 |

```text
contest/
├── README.md
├── .gitignore
├── data/
│   ├── raw/          원본 CSV 3개
│   └── processed/    위 데이터·메타데이터 6개
└── docs/
    ├── PREPROCESSING.md
    ├── 가이드북.html  기존 팀 계획
    └── 대회 공고문.hwpx  실제 파일명은 원문 유지
```

중복 제거·조인·분할 검증은 완료했다. 모델 학습과 성능 비교는 다음 단계다.
