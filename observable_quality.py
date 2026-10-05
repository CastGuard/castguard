from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from castguard.observable_quality import main

if __name__ == "__main__":
    main(ROOT)
