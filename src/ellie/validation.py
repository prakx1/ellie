"""Validate the deliberately small JSON Schema subset Ellie uses."""

import math


def validate(value, schema: dict, path: str = "$") -> None:
    if "anyOf" in schema:
        for choice in schema["anyOf"]:
            try:
                validate(value, choice, path)
                return
            except ValueError:
                pass
        raise ValueError(f"{path}: does not match any allowed shape")
    types = schema.get("type", [])
    if isinstance(types, str):
        types = [types]
    checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
              "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
              "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
              "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
              "null": lambda v: v is None}
    if types and not any(checks[t](value) for t in types):
        raise ValueError(f"{path}: expected {' or '.join(types)}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: value is outside the allowed choices")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise ValueError(f"{path}: missing properties: {', '.join(sorted(missing))}")
        if schema.get("additionalProperties") is False and set(value) - properties.keys():
            raise ValueError(f"{path}: unknown properties: {', '.join(sorted(set(value) - properties.keys()))}")
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], path + "." + key)
    if isinstance(value, list):
        for i, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{i}]")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise ValueError(f"{path}: text must not be empty")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path}: above maximum")
