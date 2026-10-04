# KAMP Note(JupyterLab)에서 실행하기

확인한 환경: Python 3.11.9 · Tesla V100 32GB · CPU 16코어 · pandas 2.1.4 · scikit-learn 1.4.2 · lightgbm 4.5.0 · catboost 1.2.5 · xgboost 2.1.1. `requirements.txt`가 이 버전과 같아서 추가 설치가 필요 없다.

1. PC의 `castguard_add.zip`을 JupyterLab 왼쪽 파일 목록에 끌어다 놓는다.
2. Launcher → **터미널**을 열고:

```bash
cd ~ && rm -rf castguard && mkdir castguard && cd castguard
unzip -q ../castguard_add.zip
python -m castguard env          # 환경 확인
python -m castguard all --jobs 16
python -m pytest -q tests        # pytest가 없으면: pip install pytest
```

3. 결과를 PC로 가져오려면 터미널에서 `cd ~/castguard && zip -qr ../castguard_results.zip reports outputs/predictions`
   → 파일 목록에서 `castguard_results.zip` 우클릭 → Download.

데이터가 작아 GPU 없이 CPU 16코어로 몇 분 안에 끝난다. GPU를 쓰려면 `configs/castguard.json`의 `"use_gpu": true`
(CatBoost·XGBoost만 해당). 노트북으로 보고 싶으면 `notebooks/run_on_kamp.ipynb`를 연다.
