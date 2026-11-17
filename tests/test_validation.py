import unittest

from ellie.validation import validate


class ValidationTests(unittest.TestCase):
    def test_nested_strict_shape_nullable_and_integer(self):
        schema = {"type": "object", "properties": {"rows": {"type": "array", "items": {"type": ["string", "null"]}}, "limit": {"type": "integer", "minimum": 1}}, "required": ["rows", "limit"], "additionalProperties": False}
        validate({"rows": ["text", None], "limit": 1}, schema)
        for value in ({"rows": []}, {"rows": [1], "limit": 1}, {"rows": [], "limit": True}, {"rows": [], "limit": 1, "extra": "no"}):
            with self.assertRaises(ValueError):
                validate(value, schema)

    def test_nullable_object(self):
        schema = {"type": ["object", "null"], "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
        validate(None, schema)
        validate({"text": "goal"}, schema)
        with self.assertRaises(ValueError):
            validate({}, schema)
