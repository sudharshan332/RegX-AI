# External Storage Register Flows

Investigation flows for failures during the **External Storage**
deployment plugin (also referred to as the
`$REGISTER_PE_ES` / `$EXTERNAL_STORAGE` step). This plugin runs
**after** the underlying PE cluster has been created and is
healthy, and registers a Pure / external array with the cluster
via the Prism Gateway endpoint
`POST /api/nutanix/v3/external_storage/create`
(served by AOS Castor / Stargate).

These failures are **not** cluster-create failures. The cluster
exists, services are up, the issue is at the AOS-side
external-storage validation or the array-side registration
itself.

> **KISS reminder** ("Keep It Simple, Stupid" — prefer the
> simplest explanation that fits the evidence): before reading
> further, run the SKILL.md "Triage Discipline (KISS First)"
> checklist. The vast majority of external-storage register
> failures are explained entirely by the deployment spec —
> most often a missing `diskless_cvm: true` flag on a test
> that needs an external storage cluster.

---

## 23. External Storage — Cluster Deployed as HCI Instead of Diskless-CVM

**RDM `failure_analysis` signature:**
```json
{
  "category": "PLUGIN",
  "error_metadata": { "RDM": { "source": "PLUGIN::EXTERNAL_STORAGE",
                               "reason": "EXTERNAL_STORAGE_REGISTER" } },
  "message": "External storage configuration failed due to exception: post request failed for https://<pe_vip>:9440/api/nutanix/v3/external_storage/create with status code 400"
}
```

**Stage signature:** Deployment proceeds normally through
imaging, cluster create, and post-cluster config. It then
fails inside the external-storage register step. RDM marks the
deployment `FAILED` and (depending on cleanup policy)
subsequently `RELEASED`.

**Deployer log signature** (in
`<id>_<retry>.txt` for the failing deployment, near the end):
```
INFO ... POST https://<pe_vip>:9440/api/nutanix/v3/external_storage/create
... <body containing array IPs / iqn / chap creds> ...
ERROR ... <<400: {"message_list":[{"message":"External storage creation not allowed in HCI mode","reason":"INVALID_REQUEST"}], "code":400, ...}
ERROR ... External storage configuration failed due to exception: post request failed ...
Traceback (most recent call last):
  File ".../external_storage_plugin.py", ...
```

**Prism Gateway log signature** (CVM side, optional — only if
deeper confirmation is needed):
- `cdp/server/castor/external_storage/external_storage_manager.cc`
  rejects the create call when `cluster.hci_enabled() == true`
  and the gflag
  `FLAGS_castor_experimental_external_storage_force_creation_on_hci`
  is `false` (default).

**Root cause:** The deployment spec did **not** request a
diskless-CVM (compute-only / external-storage) cluster, so RDM
provisioned a normal HCI cluster (CVMs own local disks and
serve storage). The test then attempted to register an external
array against that cluster. AOS Castor blocks
`external_storage/create` on HCI clusters by design, so the
Prism call returns HTTP 400 and the deployment plugin fails.

This is almost always a **spec / job-profile bug**, not a
product bug. Common origins:

- The user forgot to check the **"Enable Diskless CVM"** option
  in the JITA job profile (resources tab) when launching the
  job.
- The test's `resource_specs` snippet was copy-pasted from an
  HCI test and the `diskless_cvm` / `nested_params.diskless_cvm`
  flag was never added.
- A YAML-merging step dropped the `diskless_cvm` flag.

**Fast verification — check the spec, not the code:**

1. Pull the RDM scheduled-deployment payload:
   ```
   curl -s "https://rdm.eng.nutanix.com/api/v1/scheduled_deployments/<sd_id>" -o /tmp/rdm_sd.json
   ```
2. Inspect the resource spec and look for `diskless_cvm`:
   ```
   python3 -c "import json,sys; d=json.load(open('/tmp/rdm_sd.json'))
   for rs in d['data']['payload']['resource_specs']:
     print('top-level diskless_cvm    :', rs.get('diskless_cvm'))
     np = rs.get('nested_params') or {}
     print('nested_params diskless_cvm:', np.get('diskless_cvm'))
     print('aos build                 :', rs.get('software',{}).get('nos',{}).get('build_url'))"
   ```
3. **If both print `None` / `False` and the test is an
   external-storage test → root cause confirmed.** Stop here.
   The fix is on the requester side; do not escalate to the
   product team.

**Investigation steps (when KISS check 3 does not match):**

1. Confirm the spec **did** request `diskless_cvm: true`. If it
   did and the cluster still came up HCI, this is a different
   failure — RDM / Foundation / nested plugin failed to honor
   the diskless-CVM request. Capture the deployment DEPLOY log
   sections for "AOS Imaging" and "Cluster Create" and escalate
   to the RDM / Foundation team.
2. If the spec is correct and the cluster is genuinely
   diskless, look at the AOS side:
   - Identify the AOS GBN from
     `data.payload.resource_specs[].software.nos.build_url`.
   - Check if `FLAGS_castor_experimental_external_storage_force_creation_on_hci`
     was supposed to be set by the test's gflags config. The
     test's gflags live at e.g.
     `testcases/cdp/external_storage/<feature>/config.json`.
   - Verify whether `cluster.hci_enabled()` returned true even
     though the cluster has no data disks (would be a Castor
     bug).
3. Only then engage the Castor / external storage component
   team.

**Suggested resolution (KISS path):**

- **If the JITA job profile is the cause:** re-launch the test
  with **"Enable Diskless CVM"** checked under the resources
  selector. No code change is needed; no bug to file.
- **If the test definition's `resource_specs` lacks the flag:**
  add `diskless_cvm: true` (and propagate it into
  `nested_params.diskless_cvm` if the nested plugin uses it) in
  the test's resource spec / config and resubmit. Worth a
  quick CR.
- **If the spec is correct:** file the RCA against the team
  responsible for whichever step you identified above
  (RDM/Foundation if cluster came up HCI by mistake, Castor if
  HCI gate misfired).

**Comparison — how to tell this from other "post-cluster"
failures:**

| Symptom | This pattern (#23) | NOSCluster instantiation (#4) | Generic post-cluster (#13) |
|---|---|---|---|
| Cluster create itself | succeeded | succeeded | succeeded |
| Failure plugin | `EXTERNAL_STORAGE` | `NOS_CLUSTER` | `NOS_CLUSTER` |
| HTTP-level signature | `POST .../external_storage/create → 400` | n/a (framework `InvalidValueError`) | varies (DNS/NTP/vIP/etc.) |
| Literal error string | "External storage creation not allowed in HCI mode" | "Failed while fetching valid value for 'memory_capacity_in_bytes'" | varies |
| Most common root cause | spec missing `diskless_cvm: true` | Acropolis disconnected on freshly created cluster | post-cluster config call to PE failed |

---

## Adding New External-Storage Patterns

If you encounter an external-storage failure that does **not**
match Pattern #23, add a new pattern to this file. Likely
candidates that may surface over time:

- Array authentication failures (Pure REST 401 / invalid CHAP
  creds)
- Network unreachability between CVM and array (Pure VIP not
  routable from the CVM subnet)
- AOS-side validation failures other than the HCI gate (e.g.
  too many external storage entries, duplicate iqn)
- Castor crash / leadership flap during register

Each new pattern should follow the same structure: signature,
stage, deployer log signature, root cause, KISS verification
hint, investigation steps, suggested resolution.
