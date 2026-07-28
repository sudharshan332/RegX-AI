"""
Copyright (c) 2026 Nutanix Inc. All rights reserved.

Curates deployment failure investigation patterns based on telemetry
data stored in MongoDB. Designed to run as a periodic Jenkins job
(weekly).

Uses a two-tier promotion model based on the `user_guided` flag:

- **User-guided entries** (`user_guided: true`): Promoted immediately.
  These were created or updated during post-triage conversation with a
  human who validated the findings.

- **Skill-generated entries** (`user_guided: false`): Require 5
  occurrences from different deployments (distinct
  `scheduled_deployment_id`) spanning at least 7 days (earliest-to-
  latest timestamp gap >= 604800 seconds). This prevents burst-related
  patterns from promoting too quickly while still allowing confident
  patterns to graduate.

Both tiers apply to flow enrichments (`flow_used` with
`flow_enrichment`) and new flow candidates (`new_flow_candidate`).

Each document has a `promotion_status` field that tracks its lifecycle:
  - pending: Not yet processed by curation
  - promoted: Enrichment or new pattern written to the patterns file
  - skipped: Threshold not met, will be re-evaluated next run
  - no_enrichment: flow_used with no enrichment data

Usage:
  # Report only (read-only, no file changes)
  python curate_deployment_patterns.py --report

  # Promote graduated candidates and apply enrichments
  python curate_deployment_patterns.py --promote

  # Promote and push to Gerrit for review
  python curate_deployment_patterns.py --promote --push

  # Force-promote all pending enrichments and candidates
  # regardless of threshold (hidden option)
  python curate_deployment_patterns.py --promote --force

Author: mike.potyandy@nutanix.com
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import textwrap
from collections import defaultdict
from difflib import SequenceMatcher

_REPO_ROOT = os.environ.get('NUTEST_PATH') or os.path.abspath(
  os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from framework.lib.nulog import ERROR, INFO, STEP, WARN  # noqa: E402
from workflows.cdp.common.mongodb_client import MongoDBClient  # noqa: E402
from curation_helpers import (  # noqa: E402
  MAX_LINE_LENGTH,
  PROMOTABLE_STATUSES,
  is_duplicate_step,
  is_grep_pattern,
  is_valid_flow_name,
  mark_cluster_promoted,
  mark_enrichments_promoted,
  mark_no_enrichment,
  mark_skipped,
  update_promotion_status,
  wrap_md,
)

SKILL_DIR = os.path.dirname(os.path.dirname(
  os.path.abspath(__file__)))
PATTERNS_FILE = os.path.join(
  SKILL_DIR, 'failure-patterns-reference.md')
FLOWS_DIR = os.path.join(SKILL_DIR, 'flows')

SKILL_GENERATED_THRESHOLD = 5
TEMPORAL_SPAN_SECONDS = 604800  # 7 days
NAME_SIMILARITY_THRESHOLD = 0.6

COLLECTION_NAME = 'deployment_pattern_encounters'
DB_NAME = 'skill_telemetry'


def get_db():
  """Returns a MongoDBClient for the deployment_pattern_encounters
  collection.

  Returns:
    MongoDBClient: Connected client instance.
  """
  return MongoDBClient(collection=COLLECTION_NAME,
                       db_name=DB_NAME, track_update_times=False)


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


def partition_encounters(encounters):
  """Splits encounters into flow_used and new_flow_candidate.

  Args:
    encounters (list): List of all encounter documents.

  Returns:
    tuple: (flow_used_list, new_flow_candidate_list).
  """
  flow_used = []
  new_flow_candidates = []

  for enc in encounters:
    entry_type = enc.get('entry_type')
    if entry_type == 'flow_used':
      flow_used.append(enc)
    elif entry_type == 'new_flow_candidate':
      new_flow_candidates.append(enc)

  return flow_used, new_flow_candidates


def _deployment_key(encounter):
  """Derives a deployment identity for deduplication.

  Uses the scheduled_deployment_id as the unique deployment
  identifier. Two encounters from the same SD ID are treated as
  the same deployment event.

  Args:
    encounter (dict): Encounter document dict.

  Returns:
    str: The scheduled_deployment_id value.
  """
  return encounter.get('scheduled_deployment_id', 'unknown')


def _timestamps_span_days(encounters, min_span_seconds):
  """Checks if encounter timestamps span at least the given duration.

  Args:
    encounters (list): List of encounter documents.
    min_span_seconds (int): Minimum span in seconds between
      earliest and latest timestamps.

  Returns:
    bool: True if the span is sufficient.
  """
  timestamps = [enc.get('timestamp', 0) for enc in encounters
                if enc.get('timestamp')]
  if len(timestamps) < 2:
    return False
  return (max(timestamps) - min(timestamps)) >= min_span_seconds


def deployment_item_meets_threshold(item_info, encounters_in_group,
                                    force=False):
  """Checks if an enrichment item meets the RDM promotion threshold.

  User-guided items are promoted immediately. Skill-generated items
  need SKILL_GENERATED_THRESHOLD unique deployments spanning at
  least TEMPORAL_SPAN_SECONDS. When force=True, all items pass.

  Args:
    item_info (dict): Dict with 'sessions', 'deployment_keys',
      'has_user_guided', 'encounters'.
    encounters_in_group (list): The encounter documents contributing
      to this item.
    force (bool): If True, bypass all threshold checks.

  Returns:
    bool: True if the item is ready for promotion.
  """
  if force:
    return True

  if item_info.get('has_user_guided', False):
    return True

  unique_deployments = item_info.get('deployment_keys', set())
  if len(unique_deployments) < SKILL_GENERATED_THRESHOLD:
    return False

  return _timestamps_span_days(encounters_in_group,
                               TEMPORAL_SPAN_SECONDS)


def build_flow_usage_report(flow_used_encounters):
  """Aggregates usage stats per investigation flow.

  Args:
    flow_used_encounters (list): List of flow_used encounter
      documents.

  Returns:
    dict: Mapping of flow name to stats dict with keys
      'total_uses', 'unique_sessions', 'unique_users',
      'unique_deployments', 'last_seen', 'enrichments_count'.
  """
  stats = defaultdict(lambda: {
    'total_uses': 0, 'unique_sessions': set(), 'unique_users': set(),
    'unique_deployments': set(), 'last_seen': 0,
    'enrichments_count': 0})

  for enc in flow_used_encounters:
    raw_name = enc.get('investigation_flow')
    flow_name = (raw_name if is_valid_flow_name(raw_name)
                 else f"INVALID:{raw_name!r}")
    stats[flow_name]['total_uses'] += 1
    stats[flow_name]['unique_sessions'].add(
      enc.get('triage_id', ''))
    stats[flow_name]['unique_users'].add(enc.get('user', ''))
    stats[flow_name]['unique_deployments'].add(
      _deployment_key(enc))
    stats[flow_name]['last_seen'] = max(
      stats[flow_name]['last_seen'], enc.get('timestamp', 0))
    if enc.get('flow_enrichment'):
      stats[flow_name]['enrichments_count'] += 1

  return dict(stats)


def aggregate_enrichments(flow_used_encounters):
  """Aggregates flow enrichments across triage sessions.

  Groups enrichments by investigation flow, then by enrichment
  content. Tracks both triage_ids and deployment keys for two-tier
  thresholding, and whether any contributing session was
  user-guided.

  Args:
    flow_used_encounters (list): List of flow_used encounter
      documents.

  Returns:
    dict: Mapping of flow name to dict with keys:
          'grep_patterns' -> {pattern: {'sessions': set,
              'deployment_keys': set, 'has_user_guided': bool,
              'doc_ids': set, 'encounters': list}},
          (same structure for failure_modes, cross_service_checks,
           triage_steps, jira_keywords).
  """
  def _new_item():
    return {'sessions': set(), 'deployment_keys': set(),
            'has_user_guided': False, 'doc_ids': set(),
            'encounters': []}

  enrichments = defaultdict(lambda: {
    'grep_patterns': defaultdict(_new_item),
    'failure_modes': defaultdict(_new_item),
    'cross_service_checks': defaultdict(_new_item),
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

    dep_key = _deployment_key(enc)
    is_guided = enc.get('user_guided', False)
    doc_id = str(enc.get('_id', ''))

    def _add(category, key):
      item = enrichments[flow_name][category][key]
      item['sessions'].add(triage_id)
      item['deployment_keys'].add(dep_key)
      item['doc_ids'].add(doc_id)
      item['encounters'].append(enc)
      if is_guided:
        item['has_user_guided'] = True

    for pattern in detail.get('new_grep_patterns', []):
      _add('grep_patterns', pattern)
    for mode in detail.get('new_failure_modes', []):
      _add('failure_modes', mode)
    for check in detail.get('new_cross_service_checks', []):
      _add('cross_service_checks', check)
    for step_item in detail.get('triage_steps', []):
      _add('triage_steps', step_item)
    for keyword in detail.get('jira_keywords', []):
      _add('jira_keywords', keyword)

  return dict(enrichments)


def get_mature_enrichments(enrichments, force=False):
  """Filters enrichments that meet the promotion threshold.

  Uses two-tier logic with temporal constraint: user-guided items
  pass immediately, skill-generated items need 5 unique
  deployments spanning at least 7 days. When force=True, all
  enrichments are considered mature.

  Args:
    enrichments (dict): Output of aggregate_enrichments().
    force (bool): If True, bypass all threshold checks.

  Returns:
    dict: Same structure but only containing items that meet
      the promotion threshold.
  """
  mature = {}

  for flow_name, categories in enrichments.items():
    flow_mature = {}
    for category, items in categories.items():
      mature_items = {}
      for item, info in items.items():
        if deployment_item_meets_threshold(
            info, info.get('encounters', []),
            force=force):
          mature_items[item] = info
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
                enc.get('promotion_status', 'pending')
                in PROMOTABLE_STATUSES]

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


def cluster_meets_threshold(cluster, force=False):
  """Checks if a cluster meets the RDM promotion threshold.

  User-guided clusters (any entry has user_guided=true) are
  promoted immediately. Skill-generated clusters need
  SKILL_GENERATED_THRESHOLD unique deployments spanning at
  least TEMPORAL_SPAN_SECONDS. When force=True, all clusters
  pass.

  Args:
    cluster (list): List of encounter documents in one cluster.
    force (bool): If True, bypass all threshold checks.

  Returns:
    bool: True if the cluster is ready for promotion.
  """
  if force:
    return True

  has_user_guided = any(
    enc.get('user_guided', False) for enc in cluster)
  if has_user_guided:
    return True

  unique_deployments = {_deployment_key(enc) for enc in cluster}
  if len(unique_deployments) < SKILL_GENERATED_THRESHOLD:
    return False

  return _timestamps_span_days(cluster, TEMPORAL_SPAN_SECONDS)


def _get_existing_pattern_ids():
  """Reads existing pattern section headings from all pattern files.

  Scans failure-patterns-reference.md (index) and all flow files
  under flows/*.md for ## and ### headings.

  Returns:
    set: Normalized pattern heading IDs.
  """
  files_to_scan = []
  if os.path.exists(PATTERNS_FILE):
    files_to_scan.append(PATTERNS_FILE)
  if os.path.isdir(FLOWS_DIR):
    files_to_scan.extend(
      glob.glob(os.path.join(FLOWS_DIR, '*.md')))

  ids = set()
  for filepath in files_to_scan:
    with open(filepath, 'r') as file_handle:
      content = file_handle.read()
    headings = re.findall(
      r'^###?\s+(.+)$', content, re.MULTILINE)
    ids.update(
      re.sub(r'[^a-z0-9]+', '_', heading.lower()).strip('_')
      for heading in headings)
  return ids


def _append_pattern_to_file(section):
  """Appends a new pattern section to the index file as a staging area.

  New patterns are appended to failure-patterns-reference.md (the
  index file) for human review. The reviewer should move the pattern
  to the appropriate flow file under flows/ during code review.

  Args:
    section (str): Markdown section string to append.

  Returns:
    None
  """
  if not os.path.exists(PATTERNS_FILE):
    WARN(f"Patterns file not found: {PATTERNS_FILE}")
    return

  with open(PATTERNS_FILE, 'r') as file_handle:
    content = file_handle.read()

  content = content.rstrip('\n') + '\n\n---\n\n' + section + '\n'

  with open(PATTERNS_FILE, 'w') as file_handle:
    file_handle.write(content)


def generate_pattern_section(cluster):
  """Builds a markdown pattern section from a cluster of candidates.

  Merges subsystem descriptions, log signatures, triage steps,
  and JIRA keywords across all candidates. Wraps long lines to
  MAX_LINE_LENGTH.

  Args:
    cluster (list): List of encounter documents forming the
      cluster.

  Returns:
    tuple: (pattern_id, proposed_name, markdown_section) strings.
  """
  all_grep_patterns = []
  all_log_signatures = []
  all_triage_steps = []
  all_jira_keywords = []
  all_services = set()
  all_failure_modes = []
  all_cross_service_checks = []
  best_description = ''
  proposed_name = ''

  for enc in cluster:
    detail = enc.get('new_flow_detail') or {}

    for sig in detail.get('log_signatures', []):
      if sig not in all_log_signatures:
        all_log_signatures.append(sig)

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
      if (not is_grep_pattern(step)
          and not is_duplicate_step(step, all_triage_steps)):
        all_triage_steps.append(step)

  if not proposed_name:
    proposed_name = 'unnamed_pattern'

  pattern_id = re.sub(
    r'[^a-z0-9]+', '_', proposed_name.lower()).strip('_')

  has_guided = any(
    enc.get('user_guided', False) for enc in cluster)
  unique_deps = {_deployment_key(enc) for enc in cluster}
  wrapped_desc = wrap_md(best_description)

  promotion_reason = (
    "user-guided" if has_guided
    else f"{len(unique_deps)} deployments")

  section = (
    f"\n### {proposed_name}\n\n"
    f"*Auto-promoted from telemetry ({promotion_reason}). "
    f"Needs human review.*\n\n"
    f"**Description:** {wrapped_desc}\n")

  if all_services:
    svc_display = ', '.join(f'`{svc}`' for svc in sorted(all_services))
    section += f"\n**Related services:** {svc_display}\n"

  if all_log_signatures:
    sig_lines = '\n'.join(all_log_signatures)
    section += (
      f"\n**Log signatures:**\n\n```\n{sig_lines}\n```\n")

  if all_grep_patterns:
    grep_lines = '\n'.join(all_grep_patterns)
    section += (
      f"\n**Key grep patterns:**\n\n```bash\n{grep_lines}\n```\n")

  if all_triage_steps:
    section += "\n**Triage steps:**\n"
    for idx, step in enumerate(all_triage_steps, 1):
      wrapped_step = textwrap.fill(
        step, width=MAX_LINE_LENGTH,
        initial_indent=f"{idx}. ",
        subsequent_indent="   ")
      section += f"{wrapped_step}\n"

  if all_failure_modes:
    section += "\n**Failure propagation:**\n"
    for mode in all_failure_modes:
      wrapped_mode = textwrap.fill(
        mode, width=MAX_LINE_LENGTH,
        initial_indent="- ", subsequent_indent="  ")
      section += f"{wrapped_mode}\n"

  if all_cross_service_checks:
    section += "\n**Cross-service checks:**\n"
    for check in all_cross_service_checks:
      wrapped_check = textwrap.fill(
        check, width=MAX_LINE_LENGTH,
        initial_indent="- ", subsequent_indent="  ")
      section += f"{wrapped_check}\n"

  if all_jira_keywords:
    kw_display = ', '.join(
      f'`"{kw}"`' for kw in all_jira_keywords)
    wrapped_kw = textwrap.fill(
      kw_display, width=MAX_LINE_LENGTH)
    section += f"\n**JIRA search keywords:**\n{wrapped_kw}\n"

  return pattern_id, proposed_name, section


def push_to_gerrit():
  """Commits updated pattern files and pushes to Gerrit.

  Stages the index file and all flow files under the skill
  directory so that both new staged patterns and any manual
  flow-file edits are included in the commit.

  Returns:
    bool: True if the push succeeded.
  """
  repo_root = _REPO_ROOT

  try:
    subprocess.run(
      ['git', 'add', PATTERNS_FILE, FLOWS_DIR],
      cwd=repo_root, check=True, capture_output=True)

    commit_msg = (
      "skill-telemetry: enrich deployment failure patterns\n\n"
      "Auto-generated by curate_deployment_patterns.py.\n"
      "Pattern enrichments and/or new pattern candidates reached "
      "the promotion threshold.\n"
      "Please review the changes for accuracy.")

    subprocess.run(
      ['git', 'commit', '-m', commit_msg],
      cwd=repo_root, check=True, capture_output=True)

    result = subprocess.run(
      ['git', 'push', 'origin', 'HEAD:refs/for/master'],
      cwd=repo_root, check=True, capture_output=True, text=True)

    INFO(f"Pushed to Gerrit: {result.stdout.strip()}")
    return True

  except subprocess.CalledProcessError as error:
    ERROR(f"Git operations failed: {error}")
    if error.stderr:
      ERROR(f"stderr: {error.stderr}")
    return False


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
    header = (
      f"{'Investigation Flow':<50} {'Uses':>5} "
      f"{'Sessions':>9} {'Deploys':>8} "
      f"{'Users':>6} {'Enrichments':>12}")
    INFO(header)
    INFO('-' * len(header))

    invalid_flows = {}
    for flow_name, stats in sorted(
        usage_stats.items(),
        key=lambda item: item[1]['total_uses'],
        reverse=True):
      sessions = len(stats['unique_sessions'])
      deploys = len(stats['unique_deployments'])
      users = len(stats['unique_users'])
      INFO(
        f"{flow_name:<50} {stats['total_uses']:>5} "
        f"{sessions:>9} {deploys:>8} "
        f"{users:>6} {stats['enrichments_count']:>12}")
      if flow_name.startswith("INVALID:"):
        invalid_flows[flow_name] = stats

    if invalid_flows:
      WARN(
        "The following entries have invalid "
        "investigation_flow values. Their enrichments "
        "will NOT be promoted.")
      for flow_name, stats in invalid_flows.items():
        count = stats['enrichments_count']
        WARN(
          f"  {flow_name} ({stats['total_uses']} uses, "
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
      total_items = sum(
        len(items) for items in categories.values())
      mature_flow = mature.get(flow_name, {})
      mature_count = sum(
        len(items) for items in mature_flow.values())

      INFO(f"Flow: {flow_name}")
      INFO(f"  Total enrichment items: {total_items}")
      INFO(f"  Ready for promotion: {mature_count}")

      if mature_flow:
        for category, items in mature_flow.items():
          display_cat = category.replace('_', ' ')
          INFO(f"  Ready to apply ({display_cat}):")
          for item, info in items.items():
            reason = (
              "user-guided"
              if info.get('has_user_guided')
              else f"{len(info['deployment_keys'])} "
                   f"deployments")
            INFO(f"    - {item} ({reason})")


def print_new_flow_report(clusters):
  """Prints new flow candidate cluster analysis to stdout.

  Args:
    clusters (list): List of clusters from
      cluster_new_flow_candidates().
  """
  STEP("New Pattern Candidate Clusters")
  if not clusters:
    INFO("No new pattern candidates recorded yet.")
  else:
    for idx, cluster in enumerate(clusters, 1):
      unique_sessions = len(
        {enc.get('triage_id', '') for enc in cluster} - {''})
      unique_deploys = len(
        {_deployment_key(enc) for enc in cluster})
      has_guided = any(
        enc.get('user_guided', False) for enc in cluster)
      meets = cluster_meets_threshold(cluster)
      spans = _timestamps_span_days(
        cluster, TEMPORAL_SPAN_SECONDS)

      if meets and has_guided:
        status = "READY TO PROMOTE (user-guided)"
      elif meets:
        status = "READY TO PROMOTE (threshold met)"
      else:
        span_str = " (span < 7 days)" if not spans else ""
        status = (
          f"needs more data ({unique_deploys}/"
          f"{SKILL_GENERATED_THRESHOLD} deployments"
          f"{span_str})")

      name = _get_proposed_flow_name(cluster[0])
      detail = cluster[0].get('new_flow_detail') or {}
      description = detail.get(
        'subsystem_description', 'no description')
      guided_str = 'yes' if has_guided else 'no'

      INFO(f"Cluster {idx}: {name}")
      INFO(f"  Description: {description}")
      INFO(
        f"  Sessions: {unique_sessions}  |  "
        f"Unique deployments: {unique_deploys}  |  "
        f"User-guided: {guided_str}")
      INFO(f"  Status: {status}")


# -------------------------------------------------------------------
# Run modes
# -------------------------------------------------------------------

def run_report(db):
  """Runs the report-only mode.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
  """
  encounters = fetch_all_encounters(db)
  flow_used, new_candidates = partition_encounters(encounters)
  INFO(f"Total encounters in database: {len(encounters)}")
  INFO(f"  flow_used: {len(flow_used)}")
  INFO(f"  new_flow_candidate: {len(new_candidates)}")

  usage_stats = build_flow_usage_report(flow_used)
  print_flow_usage_report(usage_stats)

  enrichments = aggregate_enrichments(flow_used)
  mature = get_mature_enrichments(enrichments)
  print_enrichment_report(enrichments, mature)

  clusters = cluster_new_flow_candidates(new_candidates)
  print_new_flow_report(clusters)


def run_promote(db, push=False, force=False):
  """Runs the promotion mode.

  Processes new_flow_candidates and flow_used enrichments,
  updates promotion_status on all processed documents. New
  patterns are appended to failure-patterns-reference.md as
  new numbered sections.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    push (bool): Whether to push to Gerrit after promoting.
    force (bool): If True, bypass all promotion thresholds.
  """
  if force:
    WARN("Force mode enabled — bypassing all promotion "
         "thresholds.")

  encounters = fetch_all_encounters(db)
  flow_used, new_candidates = partition_encounters(encounters)
  INFO(f"Total encounters in database: {len(encounters)}")
  INFO(f"  flow_used: {len(flow_used)}")
  INFO(f"  new_flow_candidate: {len(new_candidates)}")

  usage_stats = build_flow_usage_report(flow_used)
  print_flow_usage_report(usage_stats)

  promotable_flow_used = [
    enc for enc in flow_used
    if enc.get('promotion_status', 'pending')
    in PROMOTABLE_STATUSES]

  enrichments = aggregate_enrichments(promotable_flow_used)
  mature = get_mature_enrichments(enrichments, force=force)
  print_enrichment_report(enrichments, mature)

  clusters = cluster_new_flow_candidates(new_candidates)
  print_new_flow_report(clusters)

  existing_ids = _get_existing_pattern_ids()
  promoted_count = 0

  for cluster in clusters:
    if not cluster_meets_threshold(cluster, force=force):
      skipped_ids = [
        str(enc.get('_id', '')) for enc in cluster
        if enc.get('_id')]
      update_promotion_status(db, skipped_ids, 'skipped')
      continue

    pattern_id, pattern_name, section = (
      generate_pattern_section(cluster))

    if pattern_id in existing_ids:
      INFO(
        f"Skipping '{pattern_id}' — already exists "
        f"in patterns file.")
      mark_cluster_promoted(db, cluster, pattern_id)
      continue

    INFO(f"Promoting new pattern: {pattern_id}")
    _append_pattern_to_file(section)
    mark_cluster_promoted(db, cluster, pattern_id)
    existing_ids.add(pattern_id)
    promoted_count += 1

  mark_no_enrichment(db, promotable_flow_used)

  if mature:
    STEP("Mature enrichments ready to apply")
    for flow_name, categories in mature.items():
      for category, items in categories.items():
        for item, info in items.items():
          reason = (
            "user-guided"
            if info.get('has_user_guided')
            else "force-promoted" if force
            else f"{len(info['deployment_keys'])} "
                 f"deployments")
          INFO(
            f"[{flow_name}] {category}: "
            f"{item} ({reason})")
    INFO(
      "Note: Enrichment auto-application to existing "
      "pattern sections is not yet implemented. Review "
      "the mature enrichments above and manually add "
      "them to the relevant pattern sections.")

    mark_enrichments_promoted(db, mature)
  else:
    mark_skipped(db, promotable_flow_used, mature)

  if promoted_count == 0 and not mature:
    INFO(
      "No patterns met the promotion threshold and no "
      "mature enrichments found. Nothing to do.")
  else:
    if promoted_count > 0:
      INFO(f"Promoted {promoted_count} new pattern(s).")

    if push and promoted_count > 0:
      INFO("Pushing to Gerrit...")
      push_to_gerrit()
    elif promoted_count > 0:
      INFO("Run with --push to submit to Gerrit for review.")


def main():
  """Entry point for the deployment pattern curation script."""
  parser = argparse.ArgumentParser(
    description=(
      'Curate deployment failure investigation patterns '
      'from telemetry.'))
  parser.add_argument(
    '--report', action='store_true',
    help='Print usage report and candidate clusters '
         '(read-only).')
  parser.add_argument(
    '--promote', action='store_true',
    help='Promote graduated candidates and show mature '
         'enrichments.')
  parser.add_argument(
    '--push', action='store_true',
    help='After promoting, commit and push to Gerrit '
         'for review.')
  parser.add_argument(
    '--force', action='store_true',
    help=argparse.SUPPRESS)

  args = parser.parse_args()

  if not args.report and not args.promote:
    parser.print_help()
    sys.exit(1)

  db = get_db()

  if args.report:
    run_report(db)
  elif args.promote:
    run_promote(db, push=args.push, force=args.force)


if __name__ == '__main__':
  main()
