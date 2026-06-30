"""
Copyright (c) 2026 Nutanix Inc. All rights reserved.

Generic helpers for the RDM deployment failure triage skill curation
pipeline. These were originally split out of the CDP test failure
skill's `curation_helpers.py`; only the helpers actually consumed by
`curate_deployment_patterns.py` are kept local to this skill so the
two skills' curation pipelines can evolve independently.

Author: mike.potyandy@nutanix.com
"""
import os
import re
import textwrap
import time

from framework.lib.nulog import WARN

MAX_LINE_LENGTH = 72
PROMOTABLE_STATUSES = {'pending', 'skipped', 'awaiting_manual_apply'}
INVALID_FLOW_NAMES = {'unknown', 'none', ''}

# Dry-run plumbing.  When DRY_RUN is True, DB updates are captured in
# DRY_RUN_DB_CHANGES instead of being written to MongoDB.  The curator
# CLI flips the flag via set_dry_run() when a future --dry-run mode
# is added; left intact here so the helpers remain drop-in compatible
# with the CDP-skill version.
DRY_RUN = False
DRY_RUN_DB_CHANGES = []


def set_dry_run(enabled):
  """Enables or disables dry-run mode for this module.

  Args:
    enabled (bool): True to enable dry-run capture; False to restore
      normal write behaviour and clear the buffer.
  """
  global DRY_RUN
  DRY_RUN = bool(enabled)
  DRY_RUN_DB_CHANGES.clear()


def is_valid_flow_name(name):
  """Checks whether an investigation_flow value is usable.

  Values like 'unknown', 'none', empty string, or None indicate the
  skill failed to set the field and the document should be skipped
  during aggregation.

  Args:
    name (str): The investigation_flow value to check.

  Returns:
    bool: True if the name references a real flow.
  """
  if not name:
    return False
  return name.strip().lower() not in INVALID_FLOW_NAMES


def wrap_md(text, width=MAX_LINE_LENGTH):
  """Wraps text to a max line width for markdown readability.

  Args:
    text (str): Input text string.
    width (int): Maximum characters per line.

  Returns:
    str: Wrapped text.
  """
  return textwrap.fill(text, width=width)


def normalize_for_dedup(text):
  """Strips punctuation and collapses whitespace for fuzzy compare.

  Args:
    text (str): Raw text to normalize.

  Returns:
    str: Lowercased, punctuation-stripped, whitespace-collapsed
      string.
  """
  return re.sub(
    r'\s+', ' ', re.sub(r'[^\w\s]', '', text.lower())).strip()


def is_duplicate_step(candidate, existing_steps):
  """Checks whether a candidate triage step is a semantic duplicate.

  Uses normalized substring overlap plus word-level Jaccard-like
  overlap to catch near-duplicates that would otherwise produce
  noisy patterns sections.

  Args:
    candidate (str): New triage step text.
    existing_steps (list): Already-collected triage step texts.

  Returns:
    bool: True if the candidate is a duplicate.
  """
  norm_candidate = normalize_for_dedup(candidate)
  for existing in existing_steps:
    norm_existing = normalize_for_dedup(existing)
    if (norm_candidate in norm_existing
        or norm_existing in norm_candidate):
      return True
    words_candidate = set(norm_candidate.split())
    words_existing = set(norm_existing.split())
    if not words_candidate or not words_existing:
      continue
    overlap = len(words_candidate & words_existing)
    smaller = min(len(words_candidate), len(words_existing))
    if smaller > 3 and overlap / smaller > 0.7:
      return True
  return False


def is_grep_pattern(text):
  """Heuristic: does the text look like a grep command or pattern?

  Distinguishes actual grep/regex patterns from prose triage steps
  that happen to mention log file names so the two render in
  separate sections of a generated patterns block.

  Args:
    text (str): String to check.

  Returns:
    bool: True if it looks like a grep pattern.
  """
  stripped = text.strip()
  if stripped.startswith('grep ') or stripped.startswith('grep -'):
    return True
  if '\\|' in stripped:
    return True
  prose_starts = ['check ', 'trace ', 'verify ', 'search ', 'look ',
                  'confirm ', 'review ', 'inspect ', 'ensure ',
                  'cross-reference ', 'when ', 'if ', 'for ']
  lower = stripped.lower()
  if any(lower.startswith(prefix) for prefix in prose_starts):
    return False
  if re.match(r'^[A-Z][a-z]', stripped):
    return False
  return bool(re.search(r'[.*+?|\\{}\[\]^$]', stripped))


# -------------------------------------------------------------------
# Promotion status helpers
# -------------------------------------------------------------------

def update_promotion_status(db, doc_ids, status,
                            extra_fields=None):
  """Updates promotion_status on one or more documents.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    doc_ids (list): List of document ObjectId strings.
    status (str): New promotion_status value.
    extra_fields (dict): Optional additional fields to set.
  """
  update_fields = {'promotion_status': status}
  if extra_fields:
    update_fields.update(extra_fields)

  if DRY_RUN:
    for doc_id in doc_ids:
      DRY_RUN_DB_CHANGES.append({
        'doc_id': str(doc_id),
        'set': dict(update_fields)})
    return

  from bson import ObjectId as BsonObjectId
  for doc_id in doc_ids:
    try:
      db.collection.update_one({'_id': BsonObjectId(doc_id)},
                               {'$set': update_fields})
    except Exception as error:
      WARN(f"Failed to update {doc_id}: {error}")


def mark_cluster_promoted(db, cluster, flow_id):
  """Marks candidate documents as promoted in MongoDB.

  Sets promotion_status to 'promoted' with a promoted_at timestamp
  and the flow_id they were promoted to.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    cluster (list): Encounter documents to mark.
    flow_id (str): Flow id they were promoted to.
  """
  doc_ids = [str(enc.get('_id', '')) for enc in cluster
             if enc.get('_id')]
  update_promotion_status(db, doc_ids, 'promoted', {
    'promoted_at': int(time.time()),
    'promoted_flow_id': flow_id})


def mark_enrichments_promoted(db, mature_enrichments):
  """Marks flow_used documents as promoted after enrichment apply.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    mature_enrichments (dict): Output of get_mature_enrichments().
  """
  doc_ids = set()
  for categories in mature_enrichments.values():
    for items in categories.values():
      for info in items.values():
        doc_ids.update(info.get('doc_ids', set()))

  if doc_ids:
    update_promotion_status(db, list(doc_ids), 'promoted', {
      'promoted_at': int(time.time())})


def mark_no_enrichment(db, flow_used_encounters):
  """Marks flow_used documents that have no enrichment data.

  These are flow_used entries with flow_enrichment=None that have
  promotable status. They are tracked for usage stats but have
  nothing to promote.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    flow_used_encounters (list): flow_used encounter documents.
  """
  doc_ids = []
  for enc in flow_used_encounters:
    status = enc.get('promotion_status', 'pending')
    if status not in PROMOTABLE_STATUSES:
      continue
    if not enc.get('flow_enrichment'):
      doc_id = str(enc.get('_id', ''))
      if doc_id:
        doc_ids.append(doc_id)

  if doc_ids:
    update_promotion_status(db, doc_ids, 'no_enrichment')


def mark_skipped(db, flow_used_encounters,
                 mature_enrichments):
  """Marks flow_used documents below threshold as skipped.

  Only marks promotable documents whose enrichments did not meet
  the threshold in this run.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    flow_used_encounters (list): flow_used encounter documents.
    mature_enrichments (dict): Output of get_mature_enrichments().
  """
  promoted_doc_ids = set()
  for categories in mature_enrichments.values():
    for items in categories.values():
      for info in items.values():
        promoted_doc_ids.update(
          info.get('doc_ids', set()))

  doc_ids = []
  for enc in flow_used_encounters:
    status = enc.get('promotion_status', 'pending')
    if status not in PROMOTABLE_STATUSES:
      continue
    if not enc.get('flow_enrichment'):
      continue
    doc_id = str(enc.get('_id', ''))
    if doc_id and doc_id not in promoted_doc_ids:
      doc_ids.append(doc_id)

  if doc_ids:
    update_promotion_status(db, doc_ids, 'skipped')
