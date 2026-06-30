# JIRA Report Template & Section Checklist

Reference file for `triage-cdp-test-failure`. Read this when generating the
JIRA wiki markup report (the mandatory deliverable for every triage).

---

## Report Rules

- **MANDATORY** for every triage, regardless of whether the failure is a
  product bug, test bug, resource issue, or duplicate.
- **Put the report in a code block** so the user can copy-paste it.
- **Do NOT write report files to disk** — output in chat only.
- **jira_helper.py posting**: The template below uses JIRA wiki markup.
  When posting via `jira_helper.py` (comment, create, update-existing,
  merge-duplicate), use wiki markup as-is — the helper posts directly
  to the JIRA REST API v2 which accepts wiki markup natively. **No
  Markdown conversion is needed.**

### Crediting Contributors

When findings from other engineers contributed to the triage — whether
from JIRA comments, Slack threads, code reviews, or user-provided
context — **credit them in the report**. This applies to:

- Root cause insights shared by others (e.g., an engineer identified a
  code path or failure mechanism)
- Relevant Slack discussions or JIRA comments that informed the analysis
- Prior investigations or debug sessions referenced during triage

**How to credit**: Use phrasing like "As [~username] pointed out, ..."
or "As [~username] identified in [slack thread|url], ..." to
acknowledge their contribution inline where the finding is discussed.
Do not use a separate "Credits" section — weave the attribution
naturally into the analysis where the relevant finding appears.

**When NOT to credit**: Do not credit for general information that is
part of standard documentation, gflag definitions, or publicly known
behavior. Credit is for non-obvious investigative findings that
required effort or domain expertise.

---

## Mandatory Section Checklist

Every report **must** include all of the following sections. Before outputting,
verify each one is present.

| # | Section | When to include | Content if N/A |
|---|---------|----------------|----------------|
| 1 | `h2.` Title | Always | — |
| 2 | `h3. Test Information` | Always | testcase, cluster, NOS version, build commit, GBN, date, external storage |
| 3 | `h3. Cluster Configuration` | Always | Python `pformat` dict from base config `summary` |
| 4 | `h3. Failure Summary` | Always | Root cause description |
| 5 | `h3. Integrity / Test Failures` | When `steps.log` has IO integrity or workload failures | Omit section entirely if none |
| 6 | `h3. Error Injection Timeline` | When background job logs have EI events | Omit section entirely if no EI |
| 7 | `h3. Fatal Error / Signal Error / Core` | When fatals, SIGSEGV, or cores exist | Omit section entirely if none |
| 8 | `h3. Stack Trace` | When stack traces available | Omit section entirely if none |
| 9 | `h3. Activity Trace` | When activity traces correlate with fatals | Omit section entirely if none |
| 10 | `h3. Log Context` | When ±50 lines around fatal are extracted | Omit section entirely if none |
| 11 | `h3. Related Tickets` | Always (after JIRA search) | `None found` |
| 12 | `h3. Links` | Always | Log bundle URL at minimum |

**Sections 1–4, 11, and 12 are unconditionally required.** Sections 5–10 are
conditional — include when evidence exists; omit entirely when not applicable.

---

## Template

```
h2. Bug Report: [Service] Fatal / SIGSEGV / Core - [Brief Description]

h3. Test Information
* *Testcase*: cdp.external_storage.stargate.test_smokes.TestSmokes~~~PureStorage.test_smokes___purestorage
* *Cluster*: auto_cluster_nested_69b1f7f27298f622d633d720
* *NOS Version*: el9-opt-master-b2e256c5f2a4d089a76d706ee0df43dc1686a112
* *Build Commit*: d98e3484362b45eea773dbed5832f2dbb5d50056
* *GBN*: 1773093714
* *Date*: 2026-03-12
h3. Cluster Configuration
{code:python}
{'nos_version': 'el9-opt-master-b2e256c5f2a4d089a76d706ee0df43dc1686a112',
 'nos_version_date': '2026-03-09 09:25:30+00:00',
 'gbn': '1773093714',
 'architecture': 'x86',
 'svm_cpu_count': '8',
 'huge_pages': False,
 'svm_memory_gb': '20',
 'svm_to_hyp': {'10.102.51.99': '10.102.51.100',
                '10.102.52.151': '10.102.52.152',
                '10.102.52.167': '10.102.52.173'},
 'svm_kernel_version': '5.14.0-570.58.1.el9_6.nutanix.5240.x86_64',
 'cluster_node_count': '3',
 'hypervisor': 'ahv',
 'cluster_name': 'auto_cluster_nested_69b1f7f27298f622d633d720'}
{code}

h3. Failure Summary
[Root cause description — include the full causal chain, not just the surface
error. For test validation failures, describe what the test checked, why the
underlying product state was wrong, and what caused it (e.g., "Test assertion
failed because FUSE mount was stale because xmount was killed during NOS
upgrade and not restarted"). State the disposition: product bug, test bug, or
both. Even for test bugs, explain why the product state was or was not correct.

*Reporting discipline (see SKILL.md "Reporting Discipline"):* This section
must distinguish observations from inferences and must call out gaps.

- State **observations** as facts with citations (e.g., "stargate FATAL
  at block_store.cc:718 on CVM 10.102.51.99 at 00:45:15 — errors.json").
- State **inferences** with hedging language and the evidence they rest
  on (e.g., "appears to have been triggered by ...", "is consistent
  with ...", "likely caused by ..., evidenced by shared op_id ...").
- State **gaps** explicitly. If a link in the causal chain cannot be
  verified from the available logs, write it as: "Beyond this point the
  logs do not show why X happened. Possible upstream causes: A, B.
  Needs verification by [specific check]."
- If you cannot determine the disposition (product bug vs. test bug)
  with confidence, **say so** — list the evidence for each hypothesis
  and what additional check would distinguish them. Do not pick one to
  sound decisive.

Do not present a fully-asserted chain when some links are inferred —
the user cannot tell which links to trust. A shorter, honest chain with
a labeled gap is the correct output.]

h3. Integrity / Test Failures (from steps.log)
*For each unique issue, a code block with Time, VM, Disk. Omit if none.*

1. worker_pool.cc:231] task hung — N threads, M devices
   Example: F20260312 07:14:41 worker_pool.cc:231] task: (...) is hung for more than 60 seconds
   {code}
   Time                 VM                            Disk
   2026-03-12 07:14:07  vm_io_integrity_scale-nei_0   /dev/disk/by-id/...NFS_5_0_291...
   2026-03-12 07:14:41  vm_io_integrity_scale-nei_3   /dev/disk/by-id/...NFS_5_0_301...
   {code}

h3. Error Injection Timeline
*Component = exact line from log (verbatim).*

{code}
StartTime            EndTime               Component
2026-03-12 05:19:16  2026-03-12 05:48:11   Blocking IPs: ['10.49.106.39']
2026-03-12 06:46:17  2026-03-12 07:19:17   Killing Component stargate on NOS VM: 10.122.4.28
{code}

h3. Fatal Error / Signal Error / Core
*CVMs Affected*: 10.102.51.99, 10.102.52.151
*Service*: stargate
*Time*: 2026-03-12 00:45:15
*Type*: Fatal | SIGSEGV | Core (use as applicable)

{code}
block_store.cc:718] Check failed: backing_store_->size_bytes() >= backing_store_size_bytes_
{code}
h3. Stack Trace
{code}
Obtained stack traces of threads responding to SIGPROF
===== control_1/215378 =====
#0    Object "/usr/local/nutanix/lib/libutil_net.so", at 0x7f682639aec4, in nutanix::net::GetStackTracesOfAllThreads(...)
#7    Source "/src/bigtop/util/util/block_store/block_store.cc", line 718, in nutanix::block_store::BlockStore::GlobalHeaderReadDone(...)
[... rest of stack frames ...]
{code}
h3. Activity Trace
*Correlated Activities*: op_id: -1557234, vdisk_id: 2147487115
{code}
Component: forest
2026/03/12-00:51:42.919381 236.908341 kForestUnhostOp Attributes: op_id=-1557234 vdisk_id=2147487115
           00:51:42.919381    .     0 Start
           00:51:42.919388    .     7 Acquired read id lock for backend
{code}
h3. Log Context
{code}
[±50 lines around fatal]
{code}
h3. Related Tickets
* *ENG-XXXXX*: [Summary] — *Disposition*: [Duplicate/Similar] — *Status*: [Open/Resolved/Closed] — Fix: [Gerrit XXXXXX|https://nugerrit.ntnxdpro.com/c/main/+/XXXXXX]
h3. Links
* [Log Bundle|<base_url>]
* [errors.json|http://10.41.24.49/logs/.../errors.json]
* [CVM Log|http://10.41.24.49/logs/.../10.102.51.99/service_logs/stargate.out.20260312-002450Z]
* [Base Config|http://10.41.24.49/logs/.../_base_config.json]
* [Test Log|http://10.41.24.49/logs/.../test_name/test_name.log]

Always include the **top-level log location** as the first link (labelled
"Log Bundle").

Do **NOT** include links to `background_job_logs/` directory or individual
background job log files. The relevant events are in the EI Timeline section.
```

---

## JIRA Wiki Markup Syntax

- Headers: `h2.`, `h3.`, `h4.` (not `##`, `###`)
- Bold: `*text*` (single asterisk, not `**`)
- Lists: `*` for bullets (not `-`)
- Links: `[text|url]` (pipe separator, not `[text](url)`)
- Code blocks: `{code:language}...{code}` (with language specifier)
- Literal braces inside `{{monospace}}` or `{code}` blocks: escape as `\{`
  and `\}`, otherwise JIRA interprets them as macro delimiters

---

## Testcase Name Derivation

The full testcase name is derived from the log directory path. Given:
```
.../logs/<timestamp>/cdp/external_storage/test_external_storage_smokes/TestExternalStorageSmokes~~~DellPowerStore/test_smokes___IOint_resize_snapshot_restore_ei
```
The testcase name is the path from the team root (`cdp/`) with `/` → `.`:
```
cdp.external_storage.test_external_storage_smokes.TestExternalStorageSmokes~~~DellPowerStore.test_smokes___IOint_resize_snapshot_restore_ei
```
