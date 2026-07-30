# TCMS QI Fixes - July 29, 2026

## Issue 1: TCMS QI - Overall Column Showing Incorrect Data

### Problem
The TCMS QI - Overall column in Regression Summary was showing **different data** compared to the TCMS detail page:
- API Response: 1561 total tests
- TCMS Detail Page: 1460 total tests

### Root Cause
The backend Flask API (`/mcp/regression/tcms-overall-qi`) was applying **extra filters** that are not present in the TCMS detail page:

1. `{"release_name": {"$ne": milestone}}` - Excluded tests where release_name equals milestone
2. `{"test_case.metadata.tags": {"$nin": ["SYSTEST_LONGEVITY", "LIMITED_RUNS"]}}` - Excluded longevity and limited runs tests
3. Extra broad test_sets regex without team name

### Solution
**File:** `backend/test_flask.py`

**Updated two functions:**

1. **`get_tcms_overall_qi()` endpoint** (lines 3904-3919)
   - Removed extra filters for master branch
   - Now uses only the filters that match TCMS UI:
     - `additional_data.team` filter
     - `test_case.test_sets` regex with team name
     - `test_case.deprecated` filter

2. **`_build_aggregate_payload()` helper** (lines 8970-8990)
   - Removed extra filters to ensure consistency
   - Now matches TCMS UI filtering logic

### API Example
**Before:** Applied extra filters causing discrepancy  
**After:** Matches TCMS UI filters exactly

```python
# Master branch filters (simplified):
base_conditions = [
    {"additional_data.team": f"{milestone}/{team_name}"},
    {"test_case.test_sets": {"$regex": f"test_sets/milestones/{milestone}/{team_name}/", "$options": "i"}},
    {"test_case.deprecated": False},
]
```

---

## Issue 2: "View All in JIRA" Button Failing to Load

### Problem
The "View All in JIRA" button in the TCMS QI details modal was failing to load the JIRA URL, especially with large numbers of tickets (e.g., 226 tickets).

### Root Cause
Two issues:
1. **Improper URL encoding**: Manually constructed URL with `%20` and `%2C` instead of using proper `encodeURIComponent()`
2. **URL length limits**: With 226 tickets, the URL exceeded browser limits (~2000-2048 characters)

### Solution
**File:** `src/RegressionHome.jsx` (lines 4051-4090)

**Changes:**
1. Use existing `jiraJqlUrl()` helper function for proper encoding
2. Added URL length check (>2000 chars)
3. For long URLs:
   - Use button with `openTickets()` function instead of direct link
   - Show warning message: "(URL too long, using popup)"
4. For normal URLs:
   - Use direct `<a>` tag with properly encoded URL

### Code Structure
```javascript
{(() => {
  const jiraUrl = jiraJqlUrl(tcmsDetailModal.data.unique_tickets);
  const urlLength = jiraUrl ? jiraUrl.length : 0;
  const isUrlTooLong = urlLength > 2000;
  
  if (isUrlTooLong) {
    return <button onClick={() => openTickets(...)} />;
  }
  return <a href={jiraUrl} />;
})()}
```

---

## Testing Instructions

### Test Issue 1 (TCMS QI Data)
1. **Restart the Flask backend:**
   ```bash
   # Kill the current process
   kill 1212953
   
   # Or restart via screen
   screen -r 19181.RegX_Backend
   # Then Ctrl+C and restart: python3 backend/test_flask.py
   ```

2. **Verify the fix:**
   - Open Regression Dashboard
   - Load TCMS QI - Overall for master/CDP
   - Click "Details" button
   - Compare Total Tests count with TCMS detail page
   - **Expected:** Both should show 1460 tests (not 1561)

### Test Issue 2 (View All in JIRA)
1. **Test with large ticket list (>100 tickets):**
   - Open TCMS QI - Overall details modal
   - Click "View All in JIRA" button
   - **Expected:** Should open JIRA with all tickets, showing "(URL too long, using popup)" warning

2. **Test with small ticket list (<50 tickets):**
   - Find a QI detail with fewer tickets
   - Click "View All in JIRA" link
   - **Expected:** Should open JIRA directly without warning

---

## API Comparison

### TCMS API Call (Master/CDP)
```
GET https://tcms.eng.nutanix.com/api/v1/milestone_all_test_cases/aggregate/metrics
?aggregation_field=target_package_type
&time_filter=all
&target_milestone=master
&feat_type=regression
&filters={
  "$and": [
    {"additional_data.team": "master/CDP"},
    {"test_case.test_sets": {"$regex": "test_sets/milestones/master/CDP/", "$options": "i"}},
    {"test_case.deprecated": false}
  ]
}
```

### TCMS Detail Page URL
```
https://tcms.eng.nutanix.com/#/testcases/milestone/master
?search=[{"field":"Team","op":"$eq","value":["master/CDP"]},{"field":"Test Sets","op":"$contains","value":["test_sets/milestones/master/CDP/"]}]
&tab=package_type
&pass=overall
&type=Regression
```

Both now use the same filter logic.

---

## Files Modified
1. `backend/test_flask.py` - Lines 3904-3919, 8970-8990
2. `src/RegressionHome.jsx` - Lines 4051-4090

## Deployment Notes
- **Backend restart required** for Issue 1 fix
- **Frontend rebuild required** for Issue 2 fix
  ```bash
  npm run build
  ```
- No database changes
- No breaking API changes
