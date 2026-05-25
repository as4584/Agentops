# corpus_gaps.md
# SOURCE_OF_TRUTH: GOVERNANCE
# Written by: CorpusGapHandler (corpus_gap.py)
# Do NOT edit manually except to update resolution + reviewed_by
# Owner: soul_core

## SCHEMA

gap_id:           GAP-<8 char hex>
timestamp:        ISO-8601 UTC
requesting_agent: <agent_id>
query:            <string>
top_confidence:   <float>
threshold:        <float>
delta:            <float>  # threshold - top_confidence
resolution:       UNRESOLVED | INDEXED | REJECTED
reviewed_by:      <string | null>

## GAPS

<!-- CorpusGapHandler appends below this line -->
