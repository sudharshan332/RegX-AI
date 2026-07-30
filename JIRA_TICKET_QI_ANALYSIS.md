# JIRA Ticket Level QI Calculation Analysis

## Overview

Both **Bulk Issues** and **Owner-wise Jira Ticket Breakdown** use the same QI calculation logic at the JIRA ticket level. This document explains how it works and identifies filter inconsistencies.

---

## How QI is Calculated for JIRA Tickets

### Process Flow

1. **Frontend Request** (`src/RegressionHome.jsx`, line 1267-1301)
   - User clicks "Load QI Impact" button
   - Frontend calls: `GET /mcp/regression/triage-count?include_bulk_qi=true`
   - Timeout: 5 minutes (300,000ms) due to heavy processing

2. **Backend Processing** (`backend/test_flask.py`)
   - Function: `calculate_bulk_issues_qi_impact()` (line 2159-2288)
   - For each JIRA ticket, fetches QI for ALL affected testcases from TCMS

3. **TCMS API Call** (line 2294-2353)
   - Function: `fetch_qi_from_tcms(testcase_name, milestone)`
   - Makes POST to: `{TCMS_BASE}/milestone_all_test_cases/aggregate`
   - Extracts: `operation_success_percentage` from `last_result[0].published`

4. **QI Aggregation** (line 2240-2283)
   - Calculates per-ticket metrics:
     - **Average QI**: Mean of all testcase QI values for the ticket
     - **QI Impact**: `(average_qi - 100) * nr_test_cases`
     - **Overall QI Impact**: `100 * (qi_impact / (100 * total_test_cases))`

---

## QI Calculation Formula

### Per-Ticket Metrics

```python
# For a ticket with multiple testcases:
testcase_qi = [qi1, qi2, qi3, ...]  # From TCMS API

# Step 1: Calculate average QI
average_qi = sum(testcase_qi) / len(testcase_qi)

# Step 2: Calculate QI impact
nr_test_cases = len(testcase_qi)
qi_impact = (average_qi - 100) * nr_test_cases

# Step 3: Calculate overall QI impact (relative to total testcases)
total_test_cases = total_unique_tests_in_regression_run
overall_qi_impact = 100 * (qi_impact / (100 * total_test_cases))
```

### Example Calculation

**Scenario:**
- Ticket: ENG-960228
- Affected testcases: 5
- Testcase QI values: [75, 80, 70, 85, 65]
- Total testcases in regression: 1460

**Calculation:**
```
average_qi = (75 + 80 + 70 + 85 + 65) / 5 = 75%
qi_impact = (75 - 100) * 5 = -125
overall_qi_impact = 100 * (-125 / (100 * 1460)) = -0.086%
```

This means fixing this ticket would improve overall QI by approximately 0.086%.

---

## 🔴 CRITICAL ISSUE: Incorrect TCMS Filters

### Current Filter in `fetch_qi_from_tcms()` (Line 2308-2324)

```python
payload = [{
    "$match": {
        "$and": [
            {"target_milestone": milestone},
            {"last_result": {"$elemMatch": {"pass_name": "overall"}}},
            {"deleted": False},
            {"test_case.metadata.tags": {"$nin": ["SYSTEST_LONGEVITY", "LIMITED_RUNS"]}},  # ❌ WRONG!
            {
                "$or": [
                    {"test_case.name": testcase_name},
                    {"test_case.name": {"$regex": testcase_name, "$options": "i"}}
                ]
            },
            {"test_case.deprecated": False}
        ]
    }
}]
```

### Problems

1. **Filter Inconsistency**: The function uses:
   ```python
   {"test_case.metadata.tags": {"$nin": ["SYSTEST_LONGEVITY", "LIMITED_RUNS"]}}
   ```
   
   This filter is **NOT used in TCMS UI** and was just removed from the overall QI endpoint (line 3904-3919).

2. **Missing Team Filter**: The function doesn't filter by team (`additional_data.team`), so it might fetch QI from wrong team's testcases.

3. **Missing Test Sets Filter**: The function doesn't filter by test sets (`test_case.test_sets`), which is critical for milestone-specific QI.

### Impact

- QI values for tickets may not match TCMS detail page
- QI calculations include tests that should be excluded
- Tickets show inflated or deflated QI impact
- Users see inconsistent data between RegX dashboard and TCMS

---

## Correct TCMS Filter (Should Match TCMS UI)

Based on the fix applied to `get_tcms_overall_qi()` endpoint, the correct filter should be:

```python
payload = [{
    "$match": {
        "$and": [
            {"target_milestone": milestone},
            {"last_result": {"$elemMatch": {"pass_name": "overall"}}},
            {"deleted": False},
            # No SYSTEST_LONGEVITY/LIMITED_RUNS exclusion
            {
                "$or": [
                    {"test_case.name": testcase_name},
                    {"test_case.name": {"$regex": testcase_name, "$options": "i"}}
                ]
            },
            {"test_case.deprecated": False}
        ]
    }
}]
```

**Note:** For full consistency, we should also consider adding:
- Team filter: `{"additional_data.team": f"{milestone}/{team}"}`
- Test sets filter: `{"test_case.test_sets": {"$regex": f"test_sets/milestones/{milestone}/{team}/", "$options": "i"}}`

However, these filters require additional context (team name) to be passed to `fetch_qi_from_tcms()`.

---

## Current Usage

### 1. Bulk Issues Table
**Location:** Regression Home page → Triage Count section

**Display:**
- Lists JIRA tickets with >5 affected testcases
- Shows: Ticket, Testcase Count, Average QI, QI Impact, Overall QI Impact
- Sorted by Overall QI Impact (highest first)

**Frontend:** `src/RegressionHome.jsx`, line 3061-3242

### 2. Owner-wise Jira Ticket Breakdown
**Location:** Regression Home page → Triage Count section

**Display:**
- Groups tickets by regression owner (Jira assignee)
- Shows per-ticket: QI badges, status, issue type
- Risk badges: High Risk, Medium Risk, Low Risk based on Overall QI Impact

**Frontend:** `src/RegressionHome.jsx`, line 3320-3520

**Risk Calculation:**
```javascript
const riskFromQi = (qi) => {
  if (qi === null || qi === undefined) return null;
  const absQi = Math.abs(qi);
  if (absQi >= 1.0) return "High Risk";
  if (absQi >= 0.5) return "Medium Risk";
  return "Low Risk";
};
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ User clicks "Load QI Impact"                                 │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Frontend: GET /mcp/regression/triage-count                   │
│   ?include_bulk_qi=true                                      │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Backend: calculate_bulk_issues_qi_impact()                   │
│   - Collects all unique testcases from tickets              │
│   - Parallel fetching with ThreadPoolExecutor                │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ For each testcase: fetch_qi_from_tcms()                      │
│   POST {TCMS_BASE}/milestone_all_test_cases/aggregate        │
│   ❌ Uses WRONG filters (SYSTEST_LONGEVITY exclusion)        │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Extract: operation_success_percentage                        │
│   from last_result[0].published                              │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Aggregate per ticket:                                        │
│   - average_qi                                               │
│   - qi_impact = (avg_qi - 100) * nr_test_cases              │
│   - overall_qi_impact = 100 * (qi_impact / (100 * total))   │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Return:                                                      │
│   - bulk_issues_with_qi: Per-ticket QI data                 │
│   - ticket_qi_map: All tickets QI data                      │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Frontend displays:                                           │
│   - Bulk Issues table (sorted by overall_qi_impact)         │
│   - Owner-wise breakdown (with risk badges)                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Performance Considerations

### Why QI Loading is Slow

1. **Serial API Calls**: For each unique testcase, makes a separate TCMS API call
   - Example: 100 unique testcases = 100 TCMS API calls
   - Each call takes ~100-500ms
   - Total time: 10-50 seconds

2. **Parallel Execution**: Uses `ThreadPoolExecutor` with `MAX_WORKERS` threads
   - Default MAX_WORKERS: 10 (typically)
   - Helps reduce total time but still significant

3. **No Caching**: Each request fetches fresh data from TCMS
   - No cache between requests
   - Same testcase QI fetched multiple times across different regression runs

### Optimization Ideas

1. **Batch API Calls**: Modify TCMS API to accept multiple testcases in one call
2. **Caching**: Cache testcase QI values with milestone+testcase as key (TTL: 1 hour)
3. **Background Processing**: Calculate QI asynchronously and poll for results

---

## Recommendation

### Immediate Fix Required

Update `fetch_qi_from_tcms()` function (line 2314) to remove the incorrect filter:

```python
# REMOVE THIS LINE:
{"test_case.metadata.tags": {"$nin": ["SYSTEST_LONGEVITY", "LIMITED_RUNS"]}},
```

This will align the JIRA ticket-level QI with:
- TCMS UI detail page
- Overall QI endpoint (just fixed)
- Consistent user experience

### Future Enhancement

Consider passing team context to `fetch_qi_from_tcms()` and adding:
```python
{"additional_data.team": f"{milestone}/{team}"},
{"test_case.test_sets": {"$regex": f"test_sets/milestones/{milestone}/{team}/", "$options": "i"}},
```

This will ensure QI values are team-specific and match TCMS filters exactly.

---

## Files Involved

1. **Backend:** `backend/test_flask.py`
   - Line 2159-2288: `calculate_bulk_issues_qi_impact()`
   - Line 2294-2353: `fetch_qi_from_tcms()` ← **FIX NEEDED**
   - Line 2831-2868: Triage count endpoint integration

2. **Frontend:** `src/RegressionHome.jsx`
   - Line 1267-1301: `fetchBulkIssuesQi()`
   - Line 3061-3242: Bulk Issues table display
   - Line 3320-3520: Owner-wise Jira Ticket Breakdown display

---

## Testing Checklist

After fixing the filter:

- [ ] Restart Flask backend
- [ ] Load regression dashboard
- [ ] Click "Load QI Impact" in Bulk Issues section
- [ ] Verify QI values match TCMS detail page for sample testcases
- [ ] Check Owner-wise breakdown QI badges
- [ ] Compare Overall QI Impact values before/after fix
- [ ] Document any significant changes in QI values
