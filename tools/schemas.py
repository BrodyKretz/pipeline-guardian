"""Anthropic tool schemas exposed to the patch agent's real-API path."""

PATCH_TOOLS = [
    {
        "name": "read_file",
        "description": "Read any project file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a project file.",
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
        "name": "restore_data_file",
        "description": "Restore weather_source.json to the healthy baseline.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "rewrite_pipeline_section",
        "description": "Targeted str-replace edit of pipeline.py.",
        "input_schema": {
            "type": "object",
            "properties": {
                "old_code": {"type": "string"},
                "new_code": {"type": "string"},
            },
            "required": ["old_code", "new_code"],
        },
    },
    {
        "name": "submit_patch",
        "description": "Report the fix that was applied.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]
