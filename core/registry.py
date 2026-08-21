"""Tool definitions exposed during discovery."""

DISCOVERY_TOOLS = [
    {
        "name": "act",
        "description": "Perform one action against the page using the accessibility snapshot.",
        "input_schema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["navigate", "click", "type", "select", "extract", "assert_text"]},
            "role": {"type": "string", "description": "Accessibility role; omit for navigate."},
            "name": {"type": "string", "description": "Accessible target name; omit for navigate."},
            "value": {"type": "string", "description": "URL, input text, option, or asserted substring."},
            "param_name": {"type": "string", "description": "Caller input name for typed values."},
            "extract_as": {"type": "string", "description": "Output variable name for extracted text."},
            "risk": {"type": "string", "enum": ["safe", "reversible", "irreversible"]},
            "description": {"type": "string", "description": "Reason for this step."},
        }, "required": ["action", "risk", "description"]},
    },
    {
        "name": "finish",
        "description": "Declare the reusable capability after the goal is verified.",
        "input_schema": {"type": "object", "properties": {
            "capability_name": {"type": "string"}, "capability_description": {"type": "string"},
            "checkpoint_role": {"type": "string"}, "checkpoint_name": {"type": "string"},
            "checkpoint_expected_text": {"type": "string"},
            "outputs": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "type": {"type": "string"},
                "description": {"type": "string"}, "source_extract_as": {"type": "string"},
            }, "required": ["name", "type", "description", "source_extract_as"]}},
        }, "required": ["capability_name", "capability_description", "checkpoint_expected_text", "outputs"]},
    },
    {
        "name": "escalate",
        "description": "Request human intervention when blocked or uncertain.",
        "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
    },
]
