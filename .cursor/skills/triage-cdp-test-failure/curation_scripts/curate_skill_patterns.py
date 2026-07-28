"""
Copyright (c) 2026 Nutanix Inc. All rights reserved.

Curates triage skill investigation flows based on telemetry data stored
in MongoDB. Designed to run as a periodic Jenkins job (weekly).

Uses a two-tier promotion model based on the `user_guided` flag:

- **User-guided entries** (`user_guided: true`): Promoted immediately.
  These were created or updated during post-triage conversation with a
  human who validated the findings.

- **Skill-generated entries** (`user_guided: false`): Require 3
  occurrences from different test runs (distinct `test_name` or
  `build_commit`). This ensures the auto-triage consistently reaches
  the same conclusion across different failure scenarios.

Both tiers apply to flow enrichments (`flow_used` with
`flow_enrichment`) and new flow candidates (`new_flow_candidate`).

Each document has a `promotion_status` field that tracks its lifecycle:
  - pending: Not yet processed by curation
  - promoted: Enrichment or new flow written to the patterns file
  - skipped: Threshold not met, will be re-evaluated next run
  - no_enrichment: flow_used with no enrichment data

Handles legacy documents (old per-signature schema) gracefully by
skipping them during aggregation.

Usage:
  # Report only (read-only, no file changes)
  python curate_skill_patterns.py --report

  # Promote graduated candidates and apply enrichments
  python curate_skill_patterns.py --promote

  # Promote and push to Gerrit for review
  python curate_skill_patterns.py --promote --push

Author: sam.gaver@nutanix.com
"""
import argparse
import os
import re
import subprocess
import sys
import textwrap
import time
from collections import defaultdict
from difflib import SequenceMatcher

_REPO_ROOT = os.environ.get('NUTEST_PATH') or os.path.abspath(
  os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from framework.lib.nulog import ERROR, INFO, STEP, WARN  # noqa: E402
from workflows.cdp.common.mongodb_client import MongoDBClient  # noqa: E402
import curation_helpers  # noqa: E402
from curation_helpers import (  # noqa: E402
  INVESTIGATE_FILE,
  FLOWS_DIR,
  MAX_LINE_LENGTH,
  PATTERNS_FILE,
  PROMOTABLE_STATUSES,
  README_FILE,
  SOURCEGRAPH_FILE,
  ServiceDependencyMap,
  append_flow_to_file,
  apply_ascii_diagram_patches,
  apply_component_mappings,
  apply_generic_patterns,
  format_operation_flow,
  get_existing_flow_ids,
  is_duplicate_step,
  is_grep_pattern,
  is_valid_flow_name,
  item_meets_threshold,
  mark_awaiting_manual_apply,
  mark_cluster_promoted,
  mark_enrichments_promoted,
  mark_no_enrichment,
  mark_skipped,
  normalize_dependency,
  update_promotion_status,
  wrap_md,
)

SKILL_GENERATED_THRESHOLD = 3
NAME_SIMILARITY_THRESHOLD = 0.6


def get_db():
  """Returns a MongoDBClient for the pattern_encounters collection.

  Returns:
    MongoDBClient: Connected client instance.
  """
  return MongoDBClient(collection='pattern_encounters',
                       db_name='skill_telemetry', track_update_times=False)


def fetch_all_encounters(db):
  """Fetches all encounter documents from MongoDB.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.

  Returns:
    list: All encounter documents.
  """
  return list(db.find())


def fetch_promotable_encounters(db):
  """Fetches encounters eligible for promotion processing.

  Only returns documents with promotion_status in {pending,
  skipped} or documents missing the field entirely.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.

  Returns:
    list: Promotable encounter documents.
  """
  return list(db.collection.find({
    '$or': [{'promotion_status': {
            '$in': list(PROMOTABLE_STATUSES)}},
            {'promotion_status': {'$exists': False}}]}))


def is_new_schema(encounter):
  """Checks if an encounter uses the new flow-based schema.

  Args:
    encounter (dict): Encounter document dict.

  Returns:
    bool: True if the document has entry_type field.
  """
  return 'entry_type' in encounter


def partition_encounters(encounters):
  """Splits encounters into flow_used, new_flow_candidate,
  and legacy.

  Args:
    encounters (list): List of all encounter documents.

  Returns:
    tuple: (flow_used_list, new_flow_candidate_list, legacy_list).
  """
  flow_used = []
  new_flow_candidates = []
  legacy = []

  for enc in encounters:
    if not is_new_schema(enc):
      legacy.append(enc)
    elif enc.get('entry_type') == 'flow_used':
      flow_used.append(enc)
    elif enc.get('entry_type') == 'new_flow_candidate':
      new_flow_candidates.append(enc)

  return flow_used, new_flow_candidates, legacy


def build_flow_usage_report(flow_used_encounters):
  """Aggregates usage stats per investigation flow.

  Args:
    flow_used_encounters (list): List of flow_used encounter
      documents.

  Returns:
    dict: Mapping of flow name to stats dict with keys
      'total_uses', 'unique_sessions', 'unique_users',
      'last_seen', 'enrichments_count'.
  """
  stats = defaultdict(lambda: {
    'total_uses': 0, 'unique_sessions': set(), 'unique_users': set(),
    'last_seen': 0, 'enrichments_count': 0})

  for enc in flow_used_encounters:
    raw_name = enc.get('investigation_flow')
    flow_name = (raw_name if is_valid_flow_name(raw_name)
                 else f"INVALID:{raw_name!r}")
    stats[flow_name]['total_uses'] += 1
    stats[flow_name]['unique_sessions'].add(enc.get('triage_id', ''))
    stats[flow_name]['unique_users'].add(enc.get('user', ''))
    stats[flow_name]['last_seen'] = max(stats[flow_name]['last_seen'],
                                        enc.get('timestamp', 0))
    if enc.get('flow_enrichment'):
      stats[flow_name]['enrichments_count'] += 1

  return dict(stats)


def _test_run_key(encounter):
  """Derives a test run identity for deduplication.

  Two encounters from the same test_name AND build_commit are treated
  as the same test run, even if they have different triage_ids.

  Args:
    encounter (dict): Encounter document dict.

  Returns:
    str: A composite key of test_name + build_commit.
  """
  test_name = encounter.get('test_name', 'unknown')
  build_commit = encounter.get('build_commit', 'unknown')
  return f"{test_name}|{build_commit}"


def aggregate_enrichments(flow_used_encounters):
  """Aggregates flow enrichments across triage sessions.

  Groups enrichments by investigation flow, then by enrichment
  content. Tracks both triage_ids and test run keys for two-tier
  thresholding, and whether any contributing session was
  user-guided.

  Args:
    flow_used_encounters (list): List of flow_used encounter
      documents.

  Returns:
    dict: Mapping of flow name to dict with keys:
          'grep_patterns' -> {pattern: {'sessions': set,
              'test_runs': set, 'has_user_guided': bool,
              'doc_ids': set}},
          (same structure for failure_modes, cross_service_checks,
           service_dependencies, triage_steps, jira_keywords).
  """
  def _new_item():
    return {'sessions': set(), 'test_runs': set(),
            'has_user_guided': False, 'doc_ids': set()}

  enrichments = defaultdict(lambda: {
    'grep_patterns': defaultdict(_new_item),
    'failure_modes': defaultdict(_new_item),
    'cross_service_checks': defaultdict(_new_item),
    'service_dependencies': defaultdict(_new_item),
    'triage_steps': defaultdict(_new_item),
    'jira_keywords': defaultdict(_new_item)})

  for enc in flow_used_encounters:
    flow_name = enc.get('investigation_flow')
    triage_id = enc.get('triage_id', '')
    detail = enc.get('flow_enrichment')
    if not detail or not triage_id:
      continue
    if not is_valid_flow_name(flow_name):
      continue

    test_run = _test_run_key(enc)
    is_guided = enc.get('user_guided', False)
    doc_id = str(enc.get('_id', ''))

    def _add(category, key):
      item = enrichments[flow_name][category][key]
      item['sessions'].add(triage_id)
      item['test_runs'].add(test_run)
      item['doc_ids'].add(doc_id)
      if is_guided:
        item['has_user_guided'] = True

    for pattern in detail.get('new_grep_patterns', []):
      _add('grep_patterns', pattern)
    for mode in detail.get('new_failure_modes', []):
      _add('failure_modes', mode)
    for check in detail.get('new_cross_service_checks', []):
      _add('cross_service_checks', check)
    for dep in detail.get('new_service_dependencies', []):
      dep_key = normalize_dependency(dep)
      if dep_key:
        _add('service_dependencies', dep_key)
    for step_item in detail.get('triage_steps', []):
      _add('triage_steps', step_item)
    for keyword in detail.get('jira_keywords', []):
      _add('jira_keywords', keyword)

  return dict(enrichments)


def aggregate_all_dependencies(flow_used, new_candidates):
  """Aggregates all discovered service dependencies across schemas.

  Pulls from flow_enrichment.new_service_dependencies and
  new_flow_detail.service_dependencies. Tracks user_guided and
  test_run keys for two-tier thresholding.

  Args:
    flow_used (list): List of flow_used encounter documents.
    new_candidates (list): List of new_flow_candidate encounter
      documents.

  Returns:
    dict: Mapping of dep_key to dict with 'sessions' (set),
      'test_runs' (set), 'sources' (set), 'has_user_guided'
      (bool), 'raw_deps' (list of raw dep dicts).
  """
  deps = defaultdict(lambda: {
    'sessions': set(), 'test_runs': set(), 'sources': set(),
    'has_user_guided': False, 'raw_deps': []})

  for enc in flow_used:
    triage_id = enc.get('triage_id', '')
    flow_name = enc.get('investigation_flow')
    detail = enc.get('flow_enrichment')
    if not detail or not triage_id:
      continue
    if not is_valid_flow_name(flow_name):
      continue
    test_run = _test_run_key(enc)
    is_guided = enc.get('user_guided', False)
    for dep in detail.get('new_service_dependencies', []):
      dep_key = normalize_dependency(dep)
      if dep_key:
        deps[dep_key]['sessions'].add(triage_id)
        deps[dep_key]['test_runs'].add(test_run)
        deps[dep_key]['sources'].add(flow_name)
        if isinstance(dep, dict):
          deps[dep_key]['raw_deps'].append(dep)
        if is_guided:
          deps[dep_key]['has_user_guided'] = True

  for enc in new_candidates:
    triage_id = enc.get('triage_id', '')
    detail = enc.get('new_flow_detail') or {}
    candidate_name = detail.get(
      'proposed_flow_name', 'unnamed candidate')
    test_run = _test_run_key(enc)
    is_guided = enc.get('user_guided', False)
    for dep in detail.get('service_dependencies', []):
      dep_key = normalize_dependency(dep)
      if dep_key:
        deps[dep_key]['sessions'].add(triage_id)
        deps[dep_key]['test_runs'].add(test_run)
        deps[dep_key]['sources'].add(candidate_name)
        if isinstance(dep, dict):
          deps[dep_key]['raw_deps'].append(dep)
        if is_guided:
          deps[dep_key]['has_user_guided'] = True

  return dict(deps)


def aggregate_skill_updates(encounters):
  """Aggregates top-level `skill_update` content across encounters.

  The `skill_update` field is a top-level dict on a telemetry
  document with three possible sub-lists: `ascii_diagram_patches`,
  `component_mappings`, and `generic_patterns`. Each entry is
  grouped by a content-identity key so repeated occurrences from
  distinct triage sessions aggregate toward the maturity
  threshold.

  Args:
    encounters (list): Encounter docs (both flow_used and
      new_flow_candidate types are accepted).

  Returns:
    dict: Mapping of category -> key -> info dict. `info` has
      keys `item` (raw dict), `sessions` (set), `test_runs`
      (set), `has_user_guided` (bool), `doc_ids` (set).
  """
  def _new_info():
    return {'item': None, 'sessions': set(), 'test_runs': set(),
            'has_user_guided': False, 'doc_ids': set()}

  out = {'ascii_diagram_patches': defaultdict(_new_info),
         'component_mappings': defaultdict(_new_info),
         'generic_patterns': defaultdict(_new_info)}

  for enc in encounters:
    update = enc.get('skill_update') or {}
    if not update:
      continue
    triage_id = enc.get('triage_id', '')
    test_run = _test_run_key(enc)
    is_guided = enc.get('user_guided', False)
    doc_id = str(enc.get('_id', ''))

    def _add(category, key, item):
      info = out[category][key]
      info['item'] = item
      info['sessions'].add(triage_id)
      info['test_runs'].add(test_run)
      info['doc_ids'].add(doc_id)
      if is_guided:
        info['has_user_guided'] = True

    for patch in (update.get('ascii_diagram_patches') or []):
      header = patch.get('subsystem_header', '').strip()
      if header:
        _add('ascii_diagram_patches', header, patch)
    for mapping in (update.get('component_mappings') or []):
      component = mapping.get('component', '').strip()
      if component:
        _add('component_mappings', component.lower(), mapping)
    for pattern in (update.get('generic_patterns') or []):
      title = pattern.get('title', '').strip()
      if title:
        _add('generic_patterns', title.lower(), pattern)

  return {category: dict(items) for category, items in out.items()}


def get_mature_skill_updates(skill_updates):
  """Filters skill_update items that meet the promotion threshold.

  Same two-tier rule as flow enrichments: user-guided passes
  immediately, skill-generated needs `SKILL_GENERATED_THRESHOLD`
  unique test runs.

  Args:
    skill_updates (dict): Output of `aggregate_skill_updates`.

  Returns:
    dict: Same shape, filtered to mature items only. Empty
      categories are omitted.
  """
  mature = {}
  for category, items in skill_updates.items():
    keep = {key: info for key, info in items.items()
            if item_meets_threshold(info, SKILL_GENERATED_THRESHOLD)}
    if keep:
      mature[category] = keep
  return mature


def _apply_mature_skill_updates(mature_updates):
  """Applies mature skill_update items to their target files.

  Calls the three apply helpers from curation_helpers and returns
  the set of doc_ids whose contributions were successfully
  inserted. Idempotent: items already present in the target files
  are treated as applied for promotion-status purposes.

  Args:
    mature_updates (dict): Output of `get_mature_skill_updates`.

  Returns:
    set: Doc ids that had at least one item flow through an apply
      helper (including idempotent no-ops on already-present items).
  """
  applied_doc_ids = set()
  if not mature_updates:
    return applied_doc_ids

  diagram_items = mature_updates.get('ascii_diagram_patches', {})
  diagrams = [info['item'] for info in diagram_items.values()]
  if diagrams:
    added = apply_ascii_diagram_patches(diagrams)
    if added:
      INFO(f"Auto-inserted {len(added)} ASCII sub-diagram(s) in "
           "Service Dependency Map.")
    for key, info in diagram_items.items():
      applied_doc_ids.update(info.get('doc_ids', set()))
      header = info['item'].get('subsystem_header', key)
      INFO(f"  [diagram] {header}")

  mapping_items = mature_updates.get('component_mappings', {})
  mappings = [info['item'] for info in mapping_items.values()]
  if mappings:
    added = apply_component_mappings(mappings)
    if added:
      INFO(f"Auto-inserted {len(added)} Component Mapping row(s).")
    for key, info in mapping_items.items():
      applied_doc_ids.update(info.get('doc_ids', set()))
      component = info['item'].get('component', key)
      INFO(f"  [mapping] {component}")

  pattern_items = mature_updates.get('generic_patterns', {})
  patterns = [info['item'] for info in pattern_items.values()]
  if patterns:
    added = apply_generic_patterns(patterns)
    if added:
      INFO(f"Auto-inserted {len(added)} Generic Cross-Cutting "
           "Pattern(s).")
    for key, info in pattern_items.items():
      applied_doc_ids.update(info.get('doc_ids', set()))
      title = info['item'].get('title', key)
      INFO(f"  [pattern] {title}")

  return applied_doc_ids


def _collect_enrichment_doc_ids(mature_enrichments):
  """Returns doc_ids that contributed to any mature enrichment.

  Args:
    mature_enrichments (dict): Output of get_mature_enrichments().

  Returns:
    set: Doc id strings.
  """
  doc_ids = set()
  for categories in mature_enrichments.values():
    for items in categories.values():
      for info in items.values():
        doc_ids.update(info.get('doc_ids', set()))
  return doc_ids


def get_mature_enrichments(enrichments):
  """Filters enrichments that meet the promotion threshold.

  Uses two-tier logic: user-guided items pass immediately,
  skill-generated items need 3 unique test runs.

  Args:
    enrichments (dict): Output of aggregate_enrichments().

  Returns:
    dict: Same structure but only containing items that meet
      the promotion threshold.
  """
  mature = {}

  for flow_name, categories in enrichments.items():
    flow_mature = {}
    for category, items in categories.items():
      mature_items = {item: info for item, info in items.items()
                      if item_meets_threshold(info, SKILL_GENERATED_THRESHOLD)}
      if mature_items:
        flow_mature[category] = mature_items
    if flow_mature:
      mature[flow_name] = flow_mature

  return mature


def flow_names_similar(name_a, name_b):
  """Checks if two proposed flow names are similar enough to cluster.

  Args:
    name_a (str): First flow name string.
    name_b (str): Second flow name string.

  Returns:
    bool: True if names should cluster together.
  """
  norm_a = re.sub(r'[^a-z0-9\s]', '', name_a.lower())
  norm_b = re.sub(r'[^a-z0-9\s]', '', name_b.lower())
  ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
  return ratio >= NAME_SIMILARITY_THRESHOLD


def cluster_new_flow_candidates(candidates):
  """Groups new_flow_candidate encounters by flow name similarity.

  Only considers documents with promotable status (pending/skipped
  or missing the field).

  Args:
    candidates (list): List of new_flow_candidate encounter
      documents.

  Returns:
    list: List of clusters, each a list of encounter documents.
  """
  promotable = [enc for enc in candidates if
                enc.get('promotion_status', 'pending') in PROMOTABLE_STATUSES]

  clusters = []
  assigned = set()

  for idx, enc in enumerate(promotable):
    if idx in assigned:
      continue

    cluster = [enc]
    assigned.add(idx)
    name = _get_proposed_flow_name(enc)

    for jdx in range(idx + 1, len(promotable)):
      if jdx in assigned:
        continue
      other_name = _get_proposed_flow_name(promotable[jdx])
      if flow_names_similar(name, other_name):
        cluster.append(promotable[jdx])
        assigned.add(jdx)

    clusters.append(cluster)

  return clusters


def _get_proposed_flow_name(encounter):
  """Extracts the proposed flow name from a new_flow_candidate.

  Args:
    encounter (dict): Encounter document dict.

  Returns:
    str: The proposed flow name or 'unnamed'.
  """
  detail = encounter.get('new_flow_detail') or {}
  return detail.get('proposed_flow_name', 'unnamed')


def cluster_meets_threshold(cluster):
  """Checks if a cluster meets the promotion threshold.

  User-guided clusters (any entry has user_guided=true) are
  promoted immediately. Skill-generated clusters need
  SKILL_GENERATED_THRESHOLD unique test runs.

  Args:
    cluster (list): List of encounter documents in one cluster.

  Returns:
    bool: True if the cluster is ready for promotion.
  """
  has_user_guided = any(enc.get('user_guided', False) for enc in cluster)
  if has_user_guided:
    return True

  unique_test_runs = {_test_run_key(enc) for enc in cluster}
  return len(unique_test_runs) >= SKILL_GENERATED_THRESHOLD


def generate_flow_section(cluster):
  """Builds a markdown flow section from a cluster of candidates.

  Merges subsystem descriptions, triage steps, and JIRA keywords
  across all candidates. Uses the most detailed operation flow.
  Separates grep patterns from prose triage steps. Wraps long
  lines to MAX_LINE_LENGTH.

  Args:
    cluster (list): List of encounter documents forming the
      cluster.

  Returns:
    tuple: (flow_id, proposed_name, markdown_section) strings.
  """
  all_grep_patterns = []
  all_triage_steps = []
  all_jira_keywords = []
  all_services = set()
  all_dependencies = []
  all_failure_modes = []
  all_cross_service_checks = []
  best_operation_flow = ''
  best_description = ''
  proposed_name = ''

  for enc in cluster:
    detail = enc.get('new_flow_detail') or {}

    for step in detail.get('triage_steps', []):
      if is_grep_pattern(step):
        if step not in all_grep_patterns:
          all_grep_patterns.append(step)
      elif not is_duplicate_step(step, all_triage_steps):
        all_triage_steps.append(step)

    for keyword in detail.get('jira_keywords', []):
      if keyword not in all_jira_keywords:
        all_jira_keywords.append(keyword)
    for svc in detail.get('related_services', []):
      all_services.add(svc)
    for dep in detail.get('service_dependencies', []):
      dep_key = normalize_dependency(dep)
      if dep_key and dep_key not in all_dependencies:
        all_dependencies.append(dep_key)

    op_flow = detail.get('operation_flow', '')
    if len(op_flow) > len(best_operation_flow):
      best_operation_flow = op_flow
    description = detail.get('subsystem_description', '')
    if len(description) > len(best_description):
      best_description = description
    name = detail.get('proposed_flow_name', '')
    if name and not proposed_name:
      proposed_name = name

    enrichment = enc.get('flow_enrichment') or {}
    for pattern in enrichment.get('new_grep_patterns', []):
      if pattern not in all_grep_patterns:
        all_grep_patterns.append(pattern)
    for mode in enrichment.get('new_failure_modes', []):
      if mode not in all_failure_modes:
        all_failure_modes.append(mode)
    for check in enrichment.get('new_cross_service_checks', []):
      if check not in all_cross_service_checks:
        all_cross_service_checks.append(check)
    for step in enrichment.get('triage_steps', []):
      if not is_grep_pattern(step) and \
          not is_duplicate_step(step, all_triage_steps):
        all_triage_steps.append(step)

  if not proposed_name:
    proposed_name = 'unnamed_flow'

  flow_id = re.sub(r'[^a-z0-9]+', '_', proposed_name.lower()).strip('_')

  has_guided = any(enc.get('user_guided', False) for enc in cluster)

  formatted_flow = format_operation_flow(best_operation_flow)
  wrapped_desc = wrap_md(best_description)

  promotion_reason = ("user-guided" if has_guided else
                      f"{len({_test_run_key(e) for e in cluster})} test runs")

  section = (f"\n### {proposed_name}\n\n*Auto-promoted from telemetry "
             f"({promotion_reason}). Needs human review.*\n\n"
             f"**What it does:** {wrapped_desc}\n\n"
             f"**Internal operation flow:**\n```\n{formatted_flow}\n```\n")

  if all_grep_patterns:
    grep_lines = '\n'.join(all_grep_patterns)
    section += (f"\n**Key log files and grep patterns:**\n\n"
                f"```bash\n{grep_lines}\n```\n")

  if all_triage_steps:
    section += "\n**Triage steps:**\n"
    for idx, step in enumerate(all_triage_steps, 1):
      wrapped_step = textwrap.fill(step, width=MAX_LINE_LENGTH,
                                   initial_indent=f"{idx}. ",
                                   subsequent_indent="   ")
      section += f"{wrapped_step}\n"

  if all_failure_modes:
    section += "\n**Failure propagation:**\n"
    for mode in all_failure_modes:
      wrapped_mode = textwrap.fill(mode, width=MAX_LINE_LENGTH,
                                   initial_indent="- ",
                                   subsequent_indent="  ")
      section += f"{wrapped_mode}\n"

  if all_cross_service_checks:
    section += "\n**Cross-service checks:**\n"
    for check in all_cross_service_checks:
      wrapped_check = textwrap.fill(check, width=MAX_LINE_LENGTH,
                                    initial_indent="- ",
                                    subsequent_indent="  ")
      section += f"{wrapped_check}\n"

  if all_dependencies:
    section += ("\n**Service dependencies** "
                "*(review for dependency map update):*\n")
    for dep in all_dependencies:
      section += f"- {dep}\n"

  if all_jira_keywords:
    kw_display = ', '.join(f'`"{kw}"`' for kw in all_jira_keywords)
    wrapped_kw = textwrap.fill(kw_display, width=MAX_LINE_LENGTH)
    section += (f"\n**JIRA search keywords:**\n{wrapped_kw}\n")

  return flow_id, proposed_name, section


def push_to_gerrit():
  """Commits updated patterns/flow files and pushes to Gerrit.

  Returns:
    bool: True if the push succeeded.
  """
  repo_root = _REPO_ROOT

  try:
    subprocess.run(['git', 'add', PATTERNS_FILE, FLOWS_DIR, README_FILE,
                    SOURCEGRAPH_FILE, INVESTIGATE_FILE],
                   cwd=repo_root, check=True, capture_output=True)

    commit_msg = ("skill-telemetry: enrich investigation flows\n\n"
                  "Auto-generated by curate_skill_patterns.py.\n"
                  "Flow enrichments, new flow candidates, and/or "
                  "skill_update patches (ASCII sub-diagrams, "
                  "Component Mapping rows, Generic Cross-Cutting "
                  "Patterns) reached the promotion threshold.\n"
                  "Please review the changes for accuracy.")

    subprocess.run(['git', 'commit', '-m', commit_msg],
                   cwd=repo_root, check=True, capture_output=True)

    result = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/for/master'],
                            cwd=repo_root, check=True, capture_output=True,
                            text=True)

    INFO(f"Pushed to Gerrit: {result.stdout.strip()}")
    return True

  except subprocess.CalledProcessError as error:
    ERROR(f"Git operations failed: {error}")
    if error.stderr:
      ERROR(f"stderr: {error.stderr}")
    return False


def _print_dry_run_summary():
  """Prints the DB + file changes that --dry-run would have made.

  Reads the captured changes out of the curation_helpers module-level
  buffers that `set_dry_run(True)` populated and formats them into a
  human-readable report.  Safe to call with empty buffers (prints a
  "no changes" line).
  """
  db_changes = list(curation_helpers.DRY_RUN_DB_CHANGES)
  file_changes = list(curation_helpers.DRY_RUN_FILE_CHANGES)

  STEP('-' * 60)
  STEP('DRY-RUN SUMMARY (no DB writes, no file writes)')
  STEP('-' * 60)

  INFO(f"MongoDB updates suppressed: {len(db_changes)}")
  by_status = defaultdict(list)
  for change in db_changes:
    status = change.get('set', {}).get('promotion_status', '<unset>')
    by_status[status].append(change)
  for status in sorted(by_status):
    entries = by_status[status]
    INFO(f"  -> would set promotion_status='{status}' on "
         f"{len(entries)} doc(s)")
    for change in entries[:10]:
      extras = {k: v for k, v in change['set'].items()
                if k != 'promotion_status'}
      extras_str = f"  extras={extras}" if extras else ''
      INFO(f"       _id={change['doc_id']}{extras_str}")
    if len(entries) > 10:
      INFO(f"       ... and {len(entries) - 10} more")

  INFO(f"File writes suppressed: {len(file_changes)}")
  for change in file_changes:
    rel = os.path.relpath(change['path'], _REPO_ROOT)
    action = 'create' if change['created'] else 'modify'
    delta = change['delta']
    sign = '+' if delta >= 0 else ''
    INFO(f"  -> would {action} {rel} "
         f"(lines: {change['lines_before']} -> "
         f"{change['lines_after']}, {sign}{delta})")

  if not db_changes and not file_changes:
    INFO('No changes would be made (nothing mature to promote).')


# -------------------------------------------------------------------
# Reporting functions
# -------------------------------------------------------------------

def print_flow_usage_report(usage_stats):
  """Prints a formatted flow usage report to stdout.

  Args:
    usage_stats (dict): Mapping of flow name to stats from
      build_flow_usage_report().
  """
  STEP("Investigation Flow Usage Report")
  if not usage_stats:
    INFO("No flow usage recorded yet.")
  else:
    header = (f"{'Investigation Flow':<45} {'Uses':>5} "
              f"{'Sessions':>9} {'Users':>6} {'Enrichments':>12}")
    INFO(header)
    INFO('-' * len(header))

    invalid_flows = {}
    for flow_name, stats in sorted(
        usage_stats.items(),
        key=lambda item: item[1]['total_uses'],
        reverse=True):
      sessions = len(stats['unique_sessions'])
      users = len(stats['unique_users'])
      INFO(f"{flow_name:<45} {stats['total_uses']:>5} "
           f"{sessions:>9} {users:>6} {stats['enrichments_count']:>12}")
      if flow_name.startswith("INVALID:"):
        invalid_flows[flow_name] = stats

    if invalid_flows:
      WARN("The following entries have invalid investigation_flow values. "
           "Their enrichments will NOT be promoted. This usually means "
           "the skill failed to set investigation_flow during triage.")
      for flow_name, stats in invalid_flows.items():
        count = stats['enrichments_count']
        WARN(f"  {flow_name} ({stats['total_uses']} uses, "
             f"{count} enrichments skipped)")


def print_enrichment_report(enrichments, mature):
  """Prints enrichment aggregation report to stdout.

  Args:
    enrichments (dict): Full enrichment aggregation from
      aggregate_enrichments().
    mature (dict): Mature enrichments from
      get_mature_enrichments().
  """
  STEP("Flow Enrichment Report")
  if not enrichments:
    INFO("No enrichments recorded yet.")
  else:
    for flow_name, categories in enrichments.items():
      total_items = sum(len(items) for items in categories.values())
      mature_flow = mature.get(flow_name, {})
      mature_count = sum(len(items) for items in mature_flow.values())

      INFO(f"Flow: {flow_name}")
      INFO(f"  Total enrichment items: {total_items}")
      INFO(f"  Ready for promotion: {mature_count}")

      if mature_flow:
        for category, items in mature_flow.items():
          display_category = category.replace('_', ' ')
          INFO(f"  Ready to apply ({display_category}):")
          for item, info in items.items():
            reason = ("user-guided" if info.get('has_user_guided')
                      else f"{len(info['test_runs'])} test runs")
            INFO(f"    - {item} ({reason})")


def print_new_flow_report(clusters):
  """Prints new flow candidate cluster analysis to stdout.

  Args:
    clusters (list): List of clusters from
      cluster_new_flow_candidates().
  """
  STEP("New Flow Candidate Clusters")
  if not clusters:
    INFO("No new flow candidates recorded yet.")
  else:
    for idx, cluster in enumerate(clusters, 1):
      unique_sessions = len(
        {enc.get('triage_id', '') for enc in cluster} - {''})
      unique_test_runs = len({_test_run_key(enc) for enc in cluster})
      has_guided = any(enc.get('user_guided', False) for enc in cluster)
      meets = cluster_meets_threshold(cluster)

      if meets and has_guided:
        status = "READY TO PROMOTE (user-guided)"
      elif meets:
        status = "READY TO PROMOTE (threshold met)"
      else:
        status = (f"needs more data ({unique_test_runs}/"
                  f"{SKILL_GENERATED_THRESHOLD} test runs)")

      name = _get_proposed_flow_name(cluster[0])
      detail = (cluster[0].get('new_flow_detail') or {})
      description = detail.get('subsystem_description', 'no description')
      guided_str = 'yes' if has_guided else 'no'

      INFO(f"Cluster {idx}: {name}")
      INFO(f"  Description: {description}")
      INFO(f"  Sessions: {unique_sessions}  |  Unique test runs: "
           f"{unique_test_runs}  |  User-guided: {guided_str}")
      INFO(f"  Status: {status}")


def print_dependency_report(all_deps):
  """Prints discovered service dependencies to stdout.

  Args:
    all_deps (dict): Output of aggregate_all_dependencies().
  """
  STEP("Service Dependency Discoveries")
  if not all_deps:
    INFO("No new service dependencies discovered yet.")
  else:
    for dep_key, info in sorted(
        all_deps.items(), key=lambda item: len(item[1]['sessions']),
        reverse=True):
      test_run_count = len(info.get('test_runs', set()))
      is_guided = info.get('has_user_guided', False)
      sources = ', '.join(sorted(info['sources']))
      ready = is_guided or (test_run_count >= SKILL_GENERATED_THRESHOLD)
      status_tag = ""
      if ready and is_guided:
        status_tag = " [READY - user-guided]"
      elif ready:
        status_tag = " [READY - threshold met]"
      guided_str = 'yes' if is_guided else 'no'
      INFO(f"{dep_key}")
      INFO(f"  Test runs: {test_run_count}  |  User-guided: "
           f"{guided_str}{status_tag}  |  Sources: {sources}")

    ready_deps = [
      dep_key for dep_key, info in all_deps.items()
      if info.get('has_user_guided', False)
      or len(info.get('test_runs', set())) >= SKILL_GENERATED_THRESHOLD]
    if ready_deps:
      INFO(f"{len(ready_deps)} dependency(ies) ready "
           f"for Service Dependency Map update.")


# -------------------------------------------------------------------
# Run modes
# -------------------------------------------------------------------

def _get_ready_dep_dicts(all_deps):
  """Extracts raw dependency dicts that meet promotion threshold.

  Args:
    all_deps (dict): Output of aggregate_all_dependencies().

  Returns:
    list: List of raw dep dicts (with 'from', 'to', 'context')
      that are ready for promotion.
  """
  ready = []
  seen_edges = set()
  for dep_key, info in all_deps.items():
    is_ready = (info.get('has_user_guided', False)
                or len(info.get('test_runs', set()))
                >= SKILL_GENERATED_THRESHOLD)
    if not is_ready:
      continue
    for raw_dep in info.get('raw_deps', []):
      edge = (raw_dep.get('from', '').lower(), raw_dep.get('to', '').lower())
      if edge not in seen_edges:
        ready.append(raw_dep)
        seen_edges.add(edge)
  return ready


def run_report(db):
  """Runs the report-only mode.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
  """
  encounters = fetch_all_encounters(db)
  flow_used, new_candidates, legacy = partition_encounters(encounters)
  INFO(f"Total encounters in database: {len(encounters)}")
  INFO(f"  flow_used: {len(flow_used)}")
  INFO(f"  new_flow_candidate: {len(new_candidates)}")
  INFO(f"  legacy (old schema): {len(legacy)}")

  usage_stats = build_flow_usage_report(flow_used)
  print_flow_usage_report(usage_stats)

  enrichments = aggregate_enrichments(flow_used)
  mature = get_mature_enrichments(enrichments)
  print_enrichment_report(enrichments, mature)

  all_deps = aggregate_all_dependencies(flow_used, new_candidates)
  print_dependency_report(all_deps)

  clusters = cluster_new_flow_candidates(new_candidates)
  print_new_flow_report(clusters)


def run_promote(db, push=False):
  """Runs the promotion mode.

  Processes new_flow_candidates and flow_used enrichments, updates
  promotion_status on all processed documents. Also auto-updates
  the Service Dependency Map bullet sections with ready
  dependencies.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    push (bool): Whether to push to Gerrit after promoting.
  """
  encounters = fetch_all_encounters(db)
  flow_used, new_candidates, legacy = partition_encounters(encounters)
  INFO(f"Total encounters in database: {len(encounters)}")
  INFO(f"  flow_used: {len(flow_used)}")
  INFO(f"  new_flow_candidate: {len(new_candidates)}")
  INFO(f"  legacy (old schema): {len(legacy)}")

  usage_stats = build_flow_usage_report(flow_used)
  print_flow_usage_report(usage_stats)

  promotable_flow_used = [enc for enc in flow_used if enc.get(
                          'promotion_status', 'pending') in PROMOTABLE_STATUSES]

  enrichments = aggregate_enrichments(promotable_flow_used)
  mature = get_mature_enrichments(enrichments)
  print_enrichment_report(enrichments, mature)

  all_deps = aggregate_all_dependencies(flow_used, new_candidates)
  print_dependency_report(all_deps)

  clusters = cluster_new_flow_candidates(new_candidates)
  print_new_flow_report(clusters)

  existing_ids = get_existing_flow_ids()
  promoted_count = 0

  for cluster in clusters:
    if not cluster_meets_threshold(cluster):
      skipped_ids = [str(enc.get('_id', '')) for enc in cluster
                     if enc.get('_id')]
      update_promotion_status(db, skipped_ids, 'skipped')
      continue

    flow_id, flow_name, section = generate_flow_section(cluster)

    if flow_id in existing_ids:
      INFO(f"Skipping '{flow_id}' — already exists in flow files.")
      mark_cluster_promoted(db, cluster, flow_id)
      continue

    INFO(f"Promoting new flow: {flow_id}")
    append_flow_to_file(section, flow_name=flow_name)
    mark_cluster_promoted(db, cluster, flow_id)
    existing_ids.add(flow_id)
    promoted_count += 1

  mark_no_enrichment(db, promotable_flow_used)

  ready_dep_dicts = _get_ready_dep_dicts(all_deps)
  if ready_dep_dicts:
    dep_map = ServiceDependencyMap()
    with open(PATTERNS_FILE, 'r') as file_handle:
      content = file_handle.read()

    if dep_map.parse(content):
      updated, added = dep_map.add_dependencies(content, ready_dep_dicts)
      if added:
        curation_helpers._write_file(PATTERNS_FILE, updated)
        INFO(f"Auto-updated Service Dependency Map "
             f"with {len(added)} new edge(s):")
        for from_svc, to_svc, context in added:
          INFO(f"  {from_svc} -> {to_svc}: {context}")

      missing = dep_map.validate_diagram()
      if missing:
        WARN("The following edges are in the bullet lists but not in "
             "the ASCII diagram (manual update needed — or attach an "
             "`ascii_diagram_patches` entry to the telemetry record "
             "so the curator can insert a sub-diagram next run):")
        for from_svc, to_svc in missing:
          WARN(f"  {from_svc} -> {to_svc}")

  promotable_new_candidates = [
    enc for enc in new_candidates
    if enc.get('promotion_status', 'pending') in PROMOTABLE_STATUSES]
  skill_updates = aggregate_skill_updates(
    promotable_flow_used + promotable_new_candidates)
  mature_updates = get_mature_skill_updates(skill_updates)
  applied_update_doc_ids = set()
  if mature_updates:
    STEP("Mature skill_update items ready to apply")
    applied_update_doc_ids = _apply_mature_skill_updates(mature_updates)

  manual_text_doc_ids = _collect_enrichment_doc_ids(mature)
  if mature:
    STEP("Mature flow enrichments surfaced for manual apply")
    for flow_name, categories in mature.items():
      for category, items in categories.items():
        for item, info in items.items():
          reason = ("user-guided" if info.get('has_user_guided')
                    else f"{len(info['test_runs'])} test runs")
          INFO(f"[{flow_name}] {category}: {item} ({reason})")
    INFO("Note: Auto-application for free-text flow_enrichment "
         "items (grep patterns, triage steps, failure modes, "
         "cross-service checks, JIRA keywords) is not implemented. "
         "Those records stay in 'awaiting_manual_apply' so they "
         "resurface on every run until an operator applies them.")

  update_only_doc_ids = applied_update_doc_ids - manual_text_doc_ids
  if update_only_doc_ids:
    update_promotion_status(db, list(update_only_doc_ids), 'promoted',
                            {'promoted_at': int(time.time()),
                             'promotion_source': 'skill_update'})

  if manual_text_doc_ids:
    mark_awaiting_manual_apply(db, mature)

  if not mature and not mature_updates:
    mark_skipped(db, promotable_flow_used, mature)

  if (promoted_count == 0 and not mature and not mature_updates):
    INFO("No flows met the promotion threshold and no "
         "mature enrichments found. Nothing to do.")
  else:
    if promoted_count > 0:
      INFO(f"Promoted {promoted_count} new flow(s).")

    if push and (promoted_count > 0 or mature_updates):
      INFO("Pushing to Gerrit...")
      push_to_gerrit()
    elif promoted_count > 0 or mature_updates:
      INFO("Run with --push to submit to Gerrit for review.")


def main():
  """Entry point for the curation script."""
  parser = argparse.ArgumentParser(
    description='Curate triage skill investigation flows from telemetry.')
  parser.add_argument('--report', action='store_true',
    help='Print usage report and candidate clusters (read-only).')
  parser.add_argument('--promote', action='store_true',
    help='Promote graduated candidates and show mature enrichments.')
  parser.add_argument('--push', action='store_true',
    help='After promoting, commit and push to Gerrit for review.')
  parser.add_argument('--dry-run', action='store_true',
    help='Run --promote logic without writing to MongoDB or skill '
         'files; print a summary of what would change instead. '
         'Implies no --push.')

  args = parser.parse_args()

  if args.dry_run and args.push:
    parser.error('--dry-run is incompatible with --push')
  if args.dry_run and not args.promote:
    parser.error('--dry-run has no effect without --promote')
  if not args.report and not args.promote:
    parser.print_help()
    sys.exit(1)

  db = get_db()

  if args.report:
    run_report(db)
  elif args.promote:
    if args.dry_run:
      curation_helpers.set_dry_run(True)
      try:
        run_promote(db, push=False)
      finally:
        _print_dry_run_summary()
        curation_helpers.set_dry_run(False)
    else:
      run_promote(db, push=args.push)


if __name__ == '__main__':
  main()
