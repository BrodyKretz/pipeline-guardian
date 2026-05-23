"""Anthropic tool schemas for the generative (AI-mode) agents.

Read tools return raw file text only — never any FILE_CHANGED attribution,
colors, or baseline. That separation is what keeps the agents blind to the
human-only visualization overlay.
"""

READ_TOOLS = [
    {
        "name": "read_data",
        "description": "Read the raw data source file text.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_pipeline",
        "description": "Read the raw pipeline.py source.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

CHAOS_TOOLS = READ_TOOLS + [
    {
        "name": "sabotage_file",
        "description": (
            "Write a small breaking change to ONE file "
            "(data/weather_source.json or pipeline.py)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["path", "content", "note"],
        },
    },
    {
        "name": "done",
        "description": "Call when the sabotage is complete.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

WRITE_TOOLS = READ_TOOLS + [
    {
        "name": "write_file",
        "description": (
            "Write full new content to data/weather_source.json or pipeline.py."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "dry_run",
        "description": "Run the pipeline and see the structured result.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

PATCH_TOOLS = WRITE_TOOLS + [
    {
        "name": "submit_patch",
        "description": "Report the fix applied.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]

DIAGNOSE_TOOLS = READ_TOOLS + [
    {
        "name": "submit_diagnosis",
        "description": "Submit free-form root-cause classification.",
        "input_schema": {
            "type": "object",
            "properties": {
                "failure_type": {"type": "string"},
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"},
                "suggested_fix": {"type": "string"},
            },
            "required": [
                "failure_type",
                "confidence",
                "reasoning",
                "suggested_fix",
            ],
        },
    },
]

VALIDATE_TOOLS = READ_TOOLS + [
    {
        "name": "run_output",
        "description": "Run the pipeline and read its output.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "submit_judgment",
        "description": "Judge whether the output is clean, consistent data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "passed": {"type": "boolean"},
                "reasoning": {"type": "string"},
            },
            "required": ["passed", "reasoning"],
        },
    },
]
