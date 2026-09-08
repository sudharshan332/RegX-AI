"""Pure helpers for dynamic JP clone-to, retain defaults, and catalog test selection."""

import re

NUTEST_FRAMEWORKS = ("nutest-py3-tests", "nutest-py3test")
CATALOG_ROW_STRIP_KEYS = {
    "_id", "id", "created_at", "updated_at", "created_by", "updated_by",
    "__v", "createdAt", "updatedAt", "path",
}
RETAIN_REQUIRED_STATES = ["Failed", "Aborted", "Timeout", "InfraError", "Warning"]
DEFAULT_RETAIN_EXCEPTION = "DataCorruptionError"


def is_master_branch(name):
    return (name or "").strip().lower() == "master"


def build_type_for_branch(branch):
    return "opt" if is_master_branch(branch) else "release"


def aos_version_key(branch):
    """Extract dotted version from an AOS/NOS branch name, or ``master``."""
    name = (branch or "").strip()
    if not name or is_master_branch(name):
        return "master"
    match = re.search(r"(\d+(?:\.\d+)+)", name)
    return match.group(1) if match else None


def nutest_mainline_branch(aos_branch):
    """Map clone-to AOS/NOS branch → nutest-py3-tests mainline branch.

    Patch / hotpatch AOS lines use the release mainline for NuTest:
      master → master
      ganges-7.6.0.6-stable / 7.6.0.6 → ganges-7.6-stable
      ganges-7.5.1-stable / 7.5.2 → ganges-7.5-stable
      ganges-7.6-stable / 7.6 → ganges-7.6-stable
    """
    name = (aos_branch or "").strip()
    if not name or is_master_branch(name):
        return "master"
    key = aos_version_key(name)
    if not key:
        return name
    parts = key.split(".")
    mainline = ".".join(parts[:2]) if len(parts) >= 2 else key
    return f"ganges-{mainline}-stable"


def pc_branch_search_query(clone_to):
    """JITA query for the PC branch, or None when clone-to is master (PC stays master)."""
    name = (clone_to or "").strip()
    if not name or is_master_branch(name):
        return None
    if name.lower().endswith("-pc"):
        return name
    return f"{name}-pc"


def pick_exact_branch_name(candidates, wanted):
    """Return the JITA-cased name that matches ``wanted`` exactly (case-insensitive)."""
    if not wanted:
        return None
    want = wanted.strip().lower()
    names = []
    for item in candidates or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            n = item.get("name")
            if n:
                names.append(n)
    for name in names:
        if str(name).strip().lower() == want:
            return str(name).strip()
    return None


def resolve_clone_pc_branch(clone_to, candidate_branch_names):
    """Return ``(pc_branch, unresolved_query)``.

    master → ``("master", None)``.
    Otherwise search results must contain ``{clone_to}-pc``; if missing, ``(None, query)``.
    """
    clone_to = (clone_to or "").strip()
    if not clone_to or is_master_branch(clone_to):
        return "master", None
    query = pc_branch_search_query(clone_to)
    found = pick_exact_branch_name(candidate_branch_names, query)
    if found:
        return found, None
    return None, query


def retain_test_failure_is_filled(jp_payload):
    if not isinstance(jp_payload, dict):
        return False
    existing = jp_payload.get("retain_resources_config")
    criteria = existing.get("criteria") if isinstance(existing, dict) else None
    test_failure = criteria.get("TEST_FAILURE") if isinstance(criteria, dict) else None
    if not isinstance(test_failure, dict) or not test_failure:
        return False
    params = test_failure.get("params")
    has_entity = bool(str(test_failure.get("entity") or "").strip())
    has_params = isinstance(params, dict) and bool(params)
    return has_entity or has_params


def apply_clone_retain_exceptions(jp_payload, retain_setup_on_failure=False, duration_min=72 * 60):
    """Always set Retain Test Environment on Test Failure.

    Default (Retain Setup off): ``exceptions = [DataCorruptionError]``.
    Retain Setup on: ``exceptions = []`` (blank). That is the only case DCE is omitted.
    Always overwrites TEST_FAILURE exceptions — do not skip because the source already
    has a TEST_FAILURE block.
    """
    if not isinstance(jp_payload, dict):
        return False

    existing = jp_payload.get("retain_resources_config")
    retain = dict(existing) if isinstance(existing, dict) else {}
    existing_criteria = retain.get("criteria") if isinstance(retain.get("criteria"), dict) else {}
    criteria = dict(existing_criteria)
    exceptions = [] if retain_setup_on_failure else [DEFAULT_RETAIN_EXCEPTION]

    existing_tf = criteria.get("TEST_FAILURE")
    if isinstance(existing_tf, dict) and existing_tf:
        tf = dict(existing_tf)
        params = dict(tf.get("params") if isinstance(tf.get("params"), dict) else {})
        params["duration"] = duration_min
        params["exceptions"] = list(exceptions)
        if not params.get("states_to_track"):
            params["states_to_track"] = list(RETAIN_REQUIRED_STATES)
        tf["params"] = params
        if not str(tf.get("entity") or "").strip():
            tf["entity"] = "DEPLOYMENT"
        if not tf.get("type"):
            tf["type"] = "AFTER_EACH"
        criteria["TEST_FAILURE"] = tf
    else:
        criteria["TEST_FAILURE"] = {
            "entity": "DEPLOYMENT",
            "type": "AFTER_EACH",
            "params": {
                "duration": duration_min,
                "exceptions": list(exceptions),
                "states_to_track": list(RETAIN_REQUIRED_STATES),
            },
        }
    retain["criteria"] = criteria
    jp_payload["retain_resources_config"] = retain
    return True


def apply_retain_setup_if_empty(jp_payload, duration_min=72 * 60):
    """Default retain + DataCorruptionError (Retain Setup off). Always writes exceptions."""
    return apply_clone_retain_exceptions(
        jp_payload, retain_setup_on_failure=False, duration_min=duration_min
    )


def _hit_name(hit):
    if not isinstance(hit, dict):
        return ""
    return str(hit.get("name") or hit.get("test_name") or "").strip()


def _hit_framework(hit):
    if not isinstance(hit, dict):
        return ""
    raw = hit.get("framework") or hit.get("framework_version") or hit.get("repo") or ""
    return str(raw).strip().lower()


def select_catalog_test(hits, wanted_name):
    """Pick the JITA catalog hit for ``wanted_name``. Prefer nutest-py3-tests over services."""
    wanted = (wanted_name or "").strip()
    if not wanted:
        return None
    want_l = wanted.lower()
    exact = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        name = _hit_name(hit)
        if name == wanted or name.lower() == want_l:
            exact.append(hit)
    pool = exact
    if not pool:
        return None

    def _rank(hit):
        fw = _hit_framework(hit)
        if fw in NUTEST_FRAMEWORKS or "nutest-py3" in fw:
            return 0
        if fw == "services":
            return 1
        return 2

    pool = sorted(pool, key=_rank)
    return pool[0]


def catalog_test_to_row(hit, branch):
    """Build a testset row from a catalog hit. Does not invent framework or service."""
    if not isinstance(hit, dict):
        return None
    row = {}
    for key, value in hit.items():
        if key in CATALOG_ROW_STRIP_KEYS or str(key).startswith("__"):
            continue
        row[key] = value
    name = _hit_name(hit)
    if not name:
        return None
    row["name"] = name
    if branch:
        row["branch"] = branch
    return row


def apply_destination_nos(jp_payload, nos_branch, nos_tag="Latest Smoke Passed",
                          nos_update_type="by_tag", nos_commit_id="", nos_gbn=""):
    """Overwrite NOS git branch and build type from the destination. Mutates jp_payload."""
    if not isinstance(jp_payload, dict) or not nos_branch:
        return
    git = jp_payload.get("git") or {}
    if not isinstance(git, dict):
        git = {}
    git["branch"] = nos_branch
    git.setdefault("repo", "main")
    jp_payload["git"] = git

    nos_build_type = build_type_for_branch(nos_branch)
    if nos_update_type == "by_commit":
        bs = {
            "by_commit_id": True,
            "commit_must_be_newer": False,
            "build_type": nos_build_type,
        }
        if nos_commit_id:
            bs["commit_id"] = nos_commit_id
        if nos_gbn:
            try:
                bs["gbn"] = int(nos_gbn) if isinstance(nos_gbn, str) else nos_gbn
            except (ValueError, TypeError):
                bs["gbn"] = nos_gbn
        jp_payload["build_selection"] = bs
    else:
        jp_payload["build_selection"] = {
            "by_latest_smoked": nos_tag == "Latest Smoke Passed",
            "commit_must_be_newer": False,
            "build_type": nos_build_type,
        }


def apply_destination_pc(jp_payload, pc_branch, pc_tag="Latest Smoke Passed",
                         pc_update_type="by_tag", pc_commit_id=""):
    """Overwrite Prism Central branch and build type. No-op when pc_branch is empty."""
    if not isinstance(jp_payload, dict) or not (pc_branch or "").strip():
        return
    pc_branch = pc_branch.strip()
    rmj = jp_payload.get("resource_manager_json") or {}
    if not isinstance(rmj, dict):
        rmj = {}
    rmj.setdefault("NOS_CLUSTER", {})
    pc_build = {
        "branch": pc_branch,
        "build_selection_build_type": build_type_for_branch(pc_branch),
    }
    if pc_update_type == "by_commit":
        if pc_commit_id:
            pc_build["build_selection_option"] = pc_commit_id
    else:
        pc_build["build_selection_option"] = pc_tag
    rmj["PRISM_CENTRAL"] = {"build": pc_build}
    jp_payload["resource_manager_json"] = rmj


def apply_latest_smoke_on_current_branches(jp_payload):
    """Set Latest Smoke Passed using whatever NOS/PC branches are already on the payload."""
    if not isinstance(jp_payload, dict):
        return
    git = jp_payload.get("git") or {}
    nos_branch = git.get("branch", "master") if isinstance(git, dict) else "master"
    if not isinstance(git, dict):
        git = {}
    git["branch"] = nos_branch
    git.setdefault("repo", "main")
    jp_payload["git"] = git
    jp_payload["build_selection"] = {
        "by_latest_smoked": True,
        "commit_must_be_newer": False,
        "build_type": build_type_for_branch(nos_branch),
    }

    rmj = jp_payload.get("resource_manager_json") or {}
    if not isinstance(rmj, dict):
        rmj = {}
    pc_config = rmj.get("PRISM_CENTRAL") if isinstance(rmj.get("PRISM_CENTRAL"), dict) else {}
    pc_build = pc_config.get("build") if isinstance(pc_config.get("build"), dict) else {}
    pc_branch = pc_build.get("branch") or nos_branch
    rmj.setdefault("NOS_CLUSTER", {})
    rmj["PRISM_CENTRAL"] = {
        "build": {
            "branch": pc_branch,
            "build_selection_build_type": build_type_for_branch(pc_branch),
            "build_selection_option": "Latest Smoke Passed",
        }
    }
    jp_payload["resource_manager_json"] = rmj


def set_sut_branch(jp_payload, branch):
    """Write TCMS sync branch onto system_under_test.branch without inventing a product."""
    if not isinstance(jp_payload, dict) or not (branch or "").strip():
        return
    sut = jp_payload.get("system_under_test")
    if not isinstance(sut, dict):
        sut = {}
    sut["branch"] = branch.strip()
    jp_payload["system_under_test"] = sut


# JITA additional/tester tags that should survive clone / release migration.
# Drop run-specific tags such as 752_rc1 or eg-7.6|RC3-july-13-2026.
CLONE_KEEP_ADDITIONAL_TAGS = (
    "jita3",
    "v3.1",
    "container__unlimited",
    "max_deployments__0",
    "infra__cdp",
    "py3.12",
    "jita__node_pool",
)
# TCMS sync flag on tester_tags; never strip if already present.
_TESTER_TAGS_ALWAYS_KEEP = ("official",)


def _coerce_tag_list(tags):
    """Normalize JITA tag fields (list or comma-separated string) to a list."""
    if tags is None:
        return []
    if isinstance(tags, list):
        return tags
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    return []


def _filter_kept_tags(tags, extra_keep=()):
    """Keep allowlisted tags in source order. Does not invent missing tags."""
    keep = {t.lower() for t in CLONE_KEEP_ADDITIONAL_TAGS}
    keep.update(t.lower() for t in extra_keep)
    out = []
    seen = set()
    for raw in _coerce_tag_list(tags):
        name = str(raw or "").strip()
        if not name:
            continue
        key = name.lower()
        if key not in keep or key in seen:
            continue
        out.append(name)
        seen.add(key)
    return out


def _field_is_tag_list(jp_payload, key):
    return key in jp_payload and isinstance(jp_payload.get(key), (list, str))


def clear_run_tests_with_tags(jp_payload):
    """Turn off JITA 'Run Tests With Tags' and keep only infra additional tags.

    Mutates ``jp_payload``. Does not change email, visibility, or user_groups.
    Only rewrites additional/tester tag fields when they are already present so a
    JITA GET that omitted them cannot wipe them on PUT.
    """
    if not isinstance(jp_payload, dict):
        return False
    adv = jp_payload.get("advanced_options")
    adv = dict(adv) if isinstance(adv, dict) else {}
    adv["run_tests_with_tags"] = False
    jp_payload["advanced_options"] = adv
    if _field_is_tag_list(jp_payload, "run_tests_with_additional_tags"):
        jp_payload["run_tests_with_additional_tags"] = _filter_kept_tags(
            jp_payload.get("run_tests_with_additional_tags")
        )
    if _field_is_tag_list(jp_payload, "tester_tags"):
        jp_payload["tester_tags"] = _filter_kept_tags(
            jp_payload.get("tester_tags"), extra_keep=_TESTER_TAGS_ALWAYS_KEEP
        )
    return True


DEFAULT_TEST_SERVICE = "NutestPy3Tests"


def apply_clone_test_defaults(jp_payload):
    """Set Test Service (and TCMS service) to NutestPy3Tests; skip bad tests.

    Mutates ``jp_payload``. Does not change email, visibility, or user_groups.
    Overwrites ``service`` only when Sync To TCMS is on (or it already has a
    value) so a TCMS-off cleanup PUT can still clear it.
    """
    if not isinstance(jp_payload, dict):
        return False
    jp_payload["test_service"] = DEFAULT_TEST_SERVICE
    jp_payload["skip_bad_tests"] = True
    if jp_payload.get("sync_to_tcms") or str(jp_payload.get("service") or "").strip():
        jp_payload["service"] = DEFAULT_TEST_SERVICE
    return True
