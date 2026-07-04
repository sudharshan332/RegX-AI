-- Migration: Add auto_test_details column to failed_testcase_analysis table
-- Description: Add JSON column to store auto test fix details and status
-- Created: 2026-07-05
-- Author: Enhanced Intelligent Triage Flow Implementation

-- Add auto_test_details column to failed_testcase_analysis table
-- This column stores auto test fix suggestions, status, and change request information

ALTER TABLE failed_testcase_analysis 
ADD COLUMN auto_test_details JSON DEFAULT NULL;

-- Add index for efficient querying of fix status
CREATE INDEX IF NOT EXISTS idx_failed_testcase_analysis_auto_fix_status 
ON failed_testcase_analysis ((auto_test_details->>'$.fix_status'));

-- Add index for querying by fix type
CREATE INDEX IF NOT EXISTS idx_failed_testcase_analysis_fix_type
ON failed_testcase_analysis ((auto_test_details->>'$.fix_suggestion.fix_type'));

-- Comments for documentation
COMMENT ON COLUMN failed_testcase_analysis.auto_test_details IS 
'JSON column storing auto test fix details including suggestions, status, and change requests';

-- Sample structure comment for reference:
/*
auto_test_details JSON structure:
{
  "fix_suggestion": {
    "fix_id": "string",
    "fix_type": "config_change|code_update|environment_fix|dependency_update",
    "description": "string",
    "confidence": float,
    "suggested_changes": [
      {
        "type": "string",
        "file": "string", 
        "change": "string"
      }
    ],
    "requires_approval": boolean,
    "estimated_effort": "low|medium|high",
    "risk_level": "low|medium|high",
    "test_after_fix": boolean,
    "created_at": "ISO datetime string"
  },
  "fix_status": "pending|approved|rejected|applied|verified|failed",
  "cr_number": "string",
  "approved_by": "string",
  "approved_at": "ISO datetime string",
  "fix_results": {
    "success": boolean,
    "changes_applied": integer,
    "details": "string",
    "test_results": {
      "test_executed": boolean,
      "test_passed": boolean,
      "execution_time": float,
      "test_output": "string",
      "fix_effective": boolean
    }
  },
  "created_at": "ISO datetime string",
  "updated_at": "ISO datetime string"
}
*/