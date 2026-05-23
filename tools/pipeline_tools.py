import json
import subprocess
import sys

import config
from config import OUTPUT_FILE, ROOT

# Run pipeline.run() in a fresh subprocess so AI-generated code (possible
# infinite loops, syntax errors, crashes) can never wedge the server. The
# subprocess prints the result dict as a single JSON line on stdout.
_RUNNER = (
    "import json,sys\n"
    "try:\n"
    "    import pipeline\n"
    "    print('PGRESULT'+json.dumps(pipeline.run()))\n"
    "except Exception as e:\n"
    "    print('PGRESULT'+json.dumps({'success':False,'rows_processed':0,"
    "'error':str(e),'error_type':type(e).__name__}))\n"
)


def _fail(error, error_type):
    return {
        "success": False,
        "rows_processed": 0,
        "error": error,
        "error_type": error_type,
    }


def run_pipeline():
    """Execute pipeline.run() in a timeout-bounded subprocess; return its result."""
    timeout = config.PIPELINE_TIMEOUT_SEC
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _RUNNER],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return _fail(f"pipeline exceeded {timeout}s", "Timeout")
    for line in proc.stdout.splitlines():
        if line.startswith("PGRESULT"):
            return json.loads(line[len("PGRESULT") :])
    return _fail(proc.stderr.strip() or "no result emitted", "RunnerError")


def dry_run_pipeline():
    """Run the pipeline and return the structured result (used by agents to
    test a candidate fix). Output file is overwritten; validator re-runs anyway."""
    return run_pipeline()


def get_last_output():
    if not OUTPUT_FILE.exists():
        return None
    return json.loads(OUTPUT_FILE.read_text())
