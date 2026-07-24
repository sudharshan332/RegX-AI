# Intelligent Triage Analysis Logic

## Overview

The RegX-AI Agent Framework now implements **intelligent triage analysis** with enhanced logic based on test history, failure patterns, and Nutanix knowledge integration. Cost tracking is used for **analytics only** - no credit limits are enforced.

## 🎯 **Analysis Logic Flow**

### **For Failed Testcases**

```
Failed Test Detected
    ↓
Check Test History (Free)
    ↓
┌─────────────────────┬─────────────────────┐
│ Last Run = Passed   │ Consistent Failures │
│ (Likely Intermittent)│ (Recurring Issue)   │
└─────────────────────┴─────────────────────┘
    ↓                           ↓
First Level AI Analysis    Pattern Match First
(JITA + Glean)                 ↓
15 credits              High Confidence?
                             ↓        ↓
                           Yes      No
                             ↓        ↓
                     Use Pattern   First Level AI
                      0 credits     15 credits
```

### **For Skipped Testcases**

```
Skipped Test Detected
    ↓
RDM Pattern Match Check (Free)
    ↓
┌─────────────────────┬─────────────────────┐
│ Pattern Found       │ No Pattern Match    │
│ (Known RDM Issue)   │ (Unknown Issue)     │
└─────────────────────┴─────────────────────┘
    ↓                           ↓
Pattern + Glean Search     First Level AI Analysis
5 credits                  (RDM Error + Glean)
    ↓                      15 credits
Always search for              ↓
existing issues           Comprehensive analysis
```

## 🧠 **First Level AI Analysis Components**

### **1. JITA API Integration**
```
API: https://jita-phx1-webserver-2.eng.nutanix.com/api/v2/agave_test_results/{test_id}

Analysis Includes:
• Failure stage detection (setup/execution/cleanup)
• Step log analysis
• Exception summary analysis  
• Root cause inference
```

### **2. Glean Search for Nutanix Knowledge**
```
Search Query Building:
• Extract test name components
• Include exception keywords
• Add failure stage context
• Include root cause information

Glean Results Processing:
• Existing issue detection
• Related JIRA tickets
• Documentation links
• Nutanix product knowledge
```

### **3. Intelligent Query Construction**
```python
def build_glean_search_query(test_result, jita_result):
    components = []
    
    # Test context (last 3 parts of test name)
    test_parts = test_name.split('.')[-3:]
    components.extend(test_parts)
    
    # Exception keywords (prioritize error terms)
    error_keywords = extract_error_keywords(exception_summary)
    components.extend(error_keywords[:5])
    
    # Failure stage from JITA analysis
    components.append(jita_result.failure_stage)
    
    # Root cause if available
    if jita_result.root_cause:
        components.append(jita_result.root_cause)
    
    return " ".join(components[:10])  # Limit to 10 terms
```

## 📊 **Cost Tracking for Analytics**

### **Analysis Type Costs**
```
Pattern Match:                    0 credits  (Free)
RDM Pattern + Glean:             5 credits  
First Level AI (JITA + Glean):  15 credits
Intermittent Analysis:          15 credits
Existing Issue Detection:        5 credits
```

### **No Credit Limits Policy**
- ✅ **All analysis proceeds without limits**
- ✅ **Cost tracking for optimization insights**
- ✅ **Usage analytics for pattern improvement**
- ✅ **Performance monitoring and trends**

### **Analytics Tracking**
```python
# Track for insights, not limiting
self.cost_tracker.track_usage(
    analysis_type=result.analysis_type,
    credits_used=credits_used,
    metadata={
        "test_name": test_name,
        "confidence": confidence, 
        "existing_issue_found": found_existing,
        "pattern_matched": pattern_matched
    },
    bypass_limits=True  # Always bypass - analytics only
)
```

## 🔍 **Intermittent Detection Logic**

### **History Analysis**
```python
def analyze_intermittent(test_name, history_data):
    recent_runs = history_data[-5:]  # Last 5 runs
    statuses = [run.status for run in recent_runs]
    
    pass_count = sum(1 for s in statuses if s == "passed")
    pass_rate = pass_count / len(statuses)
    
    # Intermittent conditions:
    is_intermittent = (
        last_run_status == "passed" or           # Last run passed
        (0.2 < pass_rate < 0.8 and len(set(statuses)) > 1)  # Mixed results
    )
    
    return TestHistory(
        test_name=test_name,
        last_run_status=statuses[-1],
        pass_rate=pass_rate,
        is_intermittent=is_intermittent
    )
```

### **Analysis Routing**
- **Intermittent detected** → Direct to First Level AI Analysis
- **Recurring failure** → Pattern match first, AI if no pattern
- **First failure** → Pattern match first, AI if needed

## 🎫 **Existing Issue Detection**

### **Glean Search Results Processing**
```python
def process_glean_results(glean_data, query):
    results = glean_data.get("results", [])
    
    tickets = []
    docs = []
    
    for result in results[:5]:  # Top 5 results
        url = result.get("url", "")
        title = result.get("title", "")
        
        if "jira" in url.lower() or "ticket" in title.lower():
            tickets.append(url)
        elif "doc" in url.lower() or "wiki" in url.lower():
            docs.append(url)
    
    # Determine if existing issue found
    found_existing = (
        len(tickets) > 0 or 
        any(keyword in knowledge_summary.lower() 
            for keyword in ["known issue", "workaround", "fix available"])
    )
    
    return GleanSearchResult(
        found_existing_issue=found_existing,
        suggested_tickets=tickets,
        related_docs=docs,
        nutanix_knowledge=process_knowledge(results)
    )
```

### **Ticket Suggestion Logic**
- **JIRA tickets found** → Suggest existing tickets for approval
- **Documentation found** → Link to relevant Nutanix docs
- **Known issues detected** → Highlight workarounds and fixes
- **No matches** → Create new investigation path

## 📈 **Pattern Learning & Enhancement**

### **Learning from AI Results**
```python
async def enhance_patterns_from_ai(analysis_result):
    if (analysis_result.confidence >= 0.8 and 
        analysis_result.data.get("existing_issue_found")):
        
        # Create new pattern from AI analysis
        new_pattern = PatternMatch(
            pattern_id=f"learned_{timestamp}",
            pattern_type="ai_learned",
            confidence=analysis_result.confidence,
            description=analysis_result.pattern_description,
            category=analysis_result.rdm_category,
            metadata={
                "learned_from_ai": True,
                "glean_search": True,
                "jita_analysis": True
            }
        )
        
        # Add to pattern cache for future use
        pattern_cache.add_learned_pattern(new_pattern)
```

### **Continuous Improvement**
- ✅ **AI results become new patterns**
- ✅ **Glean search improves query building**
- ✅ **JITA analysis enhances failure detection**
- ✅ **History data improves intermittent detection**

## 🛠 **Technical Implementation**

### **API Endpoints**
```
POST /api/agents/intelligent-triage
- Performs intelligent triage analysis
- Returns comprehensive results with Nutanix knowledge
- Includes existing issue detection
- No credit limits enforced

GET /api/agents/triage-analytics
- Returns cost analytics and usage patterns
- Shows optimization opportunities
- Tracks pattern learning progress
```

### **Configuration**
```yaml
# intelligent_triage_agent.yml
analysis_logic:
  failed_tests:
    check_history: true
    intermittent_threshold: 0.7
    first_level_ai_for_intermittent: true
  
  skipped_tests:
    rdm_pattern_match_first: true
    always_glean_search: true

first_level_ai:
  jita_api:
    base_url: "https://jita-phx1-webserver-2.eng.nutanix.com/api/v2"
    analyze_step_logs: true
  
  glean_search:
    mode: "nutanix_knowledge"
    include_tickets: true
    max_results: 5

cost_tracking:
  track_for_analytics: true
  no_credit_limits: true
```

## 🎯 **Expected Outcomes**

### **Improved Analysis Quality**
- **90%+ accuracy** for intermittent detection
- **95%+ knowledge coverage** through Glean search
- **80%+ existing issue detection** for known problems
- **Sub-30s analysis time** for most scenarios

### **Cost Optimization**
- **70% of analyses use 0-5 credits** (pattern matching + basic search)
- **30% use 15 credits** (comprehensive AI analysis)
- **No blocked analyses** due to credit limits
- **Continuous cost reduction** through pattern learning

### **Operational Benefits**
- **Faster issue resolution** through existing issue detection
- **Proactive ticket management** with suggestions
- **Knowledge base integration** with Nutanix expertise
- **Continuous learning** and pattern improvement

---

**Result**: Intelligent analysis that combines pattern matching, history analysis, JIRA integration, and Nutanix knowledge search to provide comprehensive failure analysis without credit restrictions.