## 1. Python Interface

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Literal, List
import datetime as dt

class PreflightGateError(Exception):
    """Base exception for preflight gate."""

class PlanIncompleteError(PreflightGateError):
    """Raised when required fields are missing or invalid."""
    def __init__(self, missing_fields: List[str]):
        self.missing_fields = missing_fields
        super().__init__(f"Missing required fields: {', '.join(missing_fields)}")

@dataclass
class ProjectManifest:
    goal: str
    primary_user: str
    success_metric: Literal["conversions", "signups", "sales", "time_on_site", "clients", "other"]
    hard_constraints: List[str]
    deadline: dt.date

class PreflightGate:
    def validate_and_save(self, manifest: Dict[str, any]) -> ProjectManifest:
        """Validate project manifest and save to project_manifest.json.
        
        Args:
            manifest: Dictionary containing project manifest data
        
        Returns:
            Validated ProjectManifest dataclass instance
        
        Raises:
            PlanIncompleteError: If any required field is missing or invalid
        """
        pass
    
    def _validate_field(self, field_name: str, value: any) -> bool:
        """Validate individual field based on rules."""
        pass
    
    def _save_manifest(self, manifest: ProjectManifest) -> None:
        """Save validated manifest to disk."""
        pass
```

## 2. Core Logic (Step by Step)

1. **Initialize validation results**
   - Create empty list `missing_fields: List[str]` to collect missing/invalid fields
   - Initialize empty set `processed_fields: set[str]` to track what was checked

2. **Define required fields with validation rules**
   - `goal`: must be non-empty string
   - `primary_user`: must be non-empty string
   - `success_metric`: must be exact value from Literal choices
   - `hard_constraints`: must be list (empty list is valid)
   - `deadline`: must be parseable as ISO date string (YYYY-MM-DD)

3. **Validate presence of all required fields**
   - For each required field name: check if key exists in `manifest`
   - If key missing, add field name to `missing_fields`
   - If key exists and value is string, check for non-empty after strip()
   - Add field name to `processed_fields` once validated

4. **Validate field formats**
   - `success_metric`: Check if value matches one of allowed choices
   - `deadline`: Attempt to parse with `dt.datetime.fromisoformat()`
   - `hard_constraints`: Ensure value is list type

5. **Check validation results**
   - If `missing_fields` is non-empty: raise `PlanIncompleteError(missing_fields)`

6. **Construct validated manifest**
   - Create `ProjectManifest` instance from validated values
   - Parse `deadline` string to `dt.date` object
   - Ensure `hard_constraints` is List[str]

7. **Save to disk**
   - Write validated manifest as JSON to `project_manifest.json`
   - Use absolute path: `cwd/project_manifest.json`
   - Include step indent for readability (pretty printing)
   - Include timestamp comment at top (# Validated at: ISO-8601 timestamp)

8. **Return validated instance**
   - Return the `ProjectManifest` dataclass instance

## 3. Edge Cases to Handle

- **Unicode handling**: Non-ASCII characters in strings (goal, primary_user, hard_constraints)
- **Leading/trailing whitespace**: Strip before validating non-empty strings
- **Case sensitivity**: `success_metric` must match exactly (lowercase)
- **Invalid date formats**: "2024/08/25", "25-08-2024", "08/25/2024" should all fail
- **Timezone information**: Reject if date string includes time/timezone (e.g., "2024-08-25T10:00:00Z")
- **Non-JSON manifest**: Handle raw dictionary input (not string)
- **Empty dictionary**: Return all 5 fields as missing
- **Type coercion failures**: Handle cases where expected string is number/int, or expected list is dict
- **Read-only filesystem**: Wrap I/O with PermissionError handling and re-raise as RuntimeError
- **File already exists**: Overwrite existing file without warning
- **Empty strings**: "   " (whitespace only) should count as empty
- **Invalid success_metric values**: Check against exact list, no substring matching
- **hard_constraints not list-like**: Dict, string, number should all fail validation

## 4. What it MUST NOT do

- Must NOT read from disk or check for existing manifests
- Must NOT generate any files other than project_manifest.json
- Must NOT print logs, warnings, or console output
- Must NOT call any external services or APIs
- Must NOT invoke LLMs (OpenAI, Claude, etc.)
- Must NOT generate code, templates, or scaffolds
- Must NOT validate file paths, URLs, or resources
- Must NOT perform security checks beyond required field validation
- Must NOT retry or recover from I/O failures
- Must NOT create directories or filesystem structure