"""실행 환경 점검 (KAMP JupyterLab 등)."""
import importlib
import platform
import shutil
import subprocess


def check() -> dict:
    info = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ["pandas", "numpy", "pyarrow", "sklearn", "lightgbm", "catboost", "xgboost", "matplotlib", "joblib"]:
        try:
            info[name] = importlib.import_module(name).__version__
        except Exception:
            info[name] = "없음"
    if shutil.which("nvidia-smi"):
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True)
        info["gpu"] = out.stdout.strip() or "확인 불가"
    else:
        info["gpu"] = "없음"
    return info
