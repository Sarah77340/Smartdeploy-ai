import json
from pathlib import Path
from jsonschema import Draft202012Validator


class SchemaValidationError(ValueError):
    pass

def validate_json_schema(obj: dict, schema_path: str) -> None:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(obj), key=lambda e: e.path)
    if errors:
        msg = "\n".join([f"- {list(e.path)}: {e.message}" for e in errors])
        raise SchemaValidationError(f"Schema validation failed:\n{msg}")
