import sys
from pathlib import Path

# Ensure project root is on sys.path so `from src import ...` works
sys.path.insert(0, str(Path(__file__).parent.parent))
