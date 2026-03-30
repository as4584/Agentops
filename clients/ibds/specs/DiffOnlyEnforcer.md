# DiffOnlyEnforcer Specification

## 1. Python Interface

```python
from typing import TypedDict
from typing_extensions import Literal

class DiffOnlyError(Exception):
    """Raised when a diff-only revision policy violation occurs."""
    pass

class WriteOperation(TypedDict):
    file_path: str
    content: str
    is_initial_scaffold: bool
    target_section: str | None

class DiffOnlyEnforcer:
    def enforce(
        self,
        operation: WriteOperation,
        revision_reason: str
    ) -> str:
        """
        Enforces diff-only revision policy.
        
        Args:
            operation: Write operation containing file_path, content, is_initial_scaffold, and target_section
            revision_reason: Reason for this revision (will be included in REVISION comment)
            
        Returns:
            content: Original content with REVISION comment attached
            
        Raises:
            DiffOnlyError: If policy violation detected
        """
        pass
```

## 2. Core Logic (Step by Step)

1. **Validate is_initial_scaffold flag**:
   - If `operation["is_initial_scaffold"]` is True, skip diff-only checks
   - If False, proceed to next validation steps

2. **Check target_section field**:
   - If `operation["target_section"]` is None or empty string (""), raise `DiffOnlyError("Missing target_section for revision")`

3. **Check content length**:
   - Count lines in `operation["content"]` by splitting on '\n'
   - If line count > 50, raise `DiffOnlyError("Content exceeds 50 lines. Use diff-only updates")`

4. **Attach REVISION comment**:
   - Construct comment: `f"<!-- REVISION: {revision_reason} --> target_section: {operation["target_section"] }"`
   - Append comment to a new line at the end of `operation["content"]`
   - Return the modified content

## 3. Edge Cases to Handle

* Empty content (0 lines) - should pass validation
* Content with only newlines - each '\n' counts as a line
* revision_reason containing newlines - sanitize by replacing with spaces
* target_section with special characters - leave as-is
* REVISION comment already present - still append new comment
* Multi-byte characters in content - count lines correctly
* Very long single line without '\n' - counts as 1 line
* Whitespace-only content - still counts as 1+ lines

## 4. What it MUST NOT do

* Read from disk (no file I/O operations)
* Call LLMs or any external services
* Modify file_path
* Validate or parse the actual content structure
* Check if target_section actually exists in the file
* Compare against previous file content
* Create directories or handle missing file paths
* Track revision history
* Generate the revision reason itself
* Process multiple files simultaneously