# JIRA Ticket QI Calculation - Quick Reference

## How QI is Calculated at JIRA Ticket Level

### Formula

```
For each JIRA ticket:
  1. Collect all affected testcases
  2. Fetch QI for each testcase from TCMS API
  3. Calculate:
     
     Average QI = Σ(testcase_qi) / number_of_testcases
     
     QI Impact = (Average QI - 100) × number_of_testcases
     
     Overall QI Impact = 100 × (QI Impact / (100 × total_testcases_in_regression))
```

### Example

**Ticket:** ENG-960228  
**Testcases:** 5 tests with QI values [75, 80, 70, 85, 65]  
**Total regression tests:** 1460

```
Average QI = (75 + 80 + 70 + 85 + 65) / 5 = 75%

QI Impact = (75 - 100) × 5 = -125

Overall QI Impact = 100 × (-125 / (100 × 1460))
                  = 100 × (-125 / 146000)
                  = -0.086%
```

**Interpretation:** Fixing this ticket would improve overall regression QI by 0.086%

---

## Risk Classification

Based on **Overall QI Impact**:

| Risk Level | Threshold | Color | Action |
|------------|-----------|-------|--------|
| 🔴 High Risk | \|QI Impact\| ≥ 1.0% | Red | Fix immediately |
| 🟡 Medium Risk | \|QI Impact\| ≥ 0.5% | Yellow | Fix soon |
| 🟢 Low Risk | \|QI Impact\| < 0.5% | Green | Fix when possible |

---

## TCMS Filter Issue (FIXED)

### ❌ What Was Wrong

The `fetch_qi_from_tcms()` function was using this filter:

```python
{"test_case.metadata.tags": {"$nin": ["SYSTEST_LONGEVITY", "LIMITED_RUNS"]}}
```

This filter **excluded tests** that TCMS UI **includes**, causing QI values to be inconsistent.

### ✅ What Was Fixed

**Removed** the incorrect filter. Now uses only:

```python
{
  "$and": [
    {"target_milestone": milestone},
    {"last_result": {"$elemMatch": {"pass_name": "overall"}}},
    {"deleted": False},
    {"test_case.name": testcase_name},
    {"test_case.deprecated": False}
  ]
}
```

Matches TCMS UI exactly! ✅

---

## Where This is Used

### 1. Bulk Issues Table
Shows tickets with >5 testcases, sorted by Overall QI Impact

**Location:** Triage Count section → "Bulk Issues (tickets with >5 testcases)"

### 2. Owner-wise Jira Ticket Breakdown
Shows tickets grouped by owner with risk badges

**Location:** Triage Count section → "Owner-wise Jira Ticket Breakdown"

---

## Loading QI Data

1. Click **"Load QI Impact"** button
2. Wait 2-5 minutes (fetches QI for each testcase from TCMS)
3. Table updates with QI values and risk badges

**Note:** This is a heavy operation! Only load when needed.

---

## After the Fix

**Before:**
- QI values: Inconsistent with TCMS UI ❌
- Risk badges: Inaccurate ❌
- Total tests: Wrong (1561 instead of 1460) ❌

**After:**
- QI values: Match TCMS UI exactly ✅
- Risk badges: Accurate ✅
- Total tests: Correct (1460) ✅

---

## Quick Test

1. Load Regression Dashboard
2. Click "Load QI Impact" in Bulk Issues
3. Pick a ticket (e.g., ENG-960228)
4. Note the Average QI
5. Go to TCMS and find those testcases
6. Verify Average QI matches ✅

---

**Files Modified:**
- `backend/test_flask.py` (line 2306-2324, 3904-3919, 8970-8990)

**Restart Required:** YES (Flask backend)
