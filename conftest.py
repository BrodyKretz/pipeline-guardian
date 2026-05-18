import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Pin the key empty BEFORE config.py runs load_dotenv(). python-dotenv uses
# override=False, so a real key in a developer's .env can't leak into the
# test suite and flip mode/has_key assertions. (Set this in your shell to a
# real key only if you intentionally want to exercise the live API in tests.)
os.environ.setdefault("ANTHROPIC_API_KEY", "")
