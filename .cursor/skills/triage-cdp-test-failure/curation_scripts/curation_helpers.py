"""
Copyright (c) 2026 Nutanix Inc. All rights reserved.

Generic helpers for the triage skill curation pipeline.

Contains text/markdown utilities, promotion status management,
file I/O for the patterns reference file, and the
ServiceDependencyMap class for auto-updating the service
dependency map section.
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
# DRY_RUN_DB_CHANGES instead of being written, and file writes are
# captured in DRY_RUN_FILE_CHANGES.  The curator CLI flips the flag
# via set_dry_run() and inspects the captured changes after a run.
DRY_RUN = False
DRY_RUN_DB_CHANGES = []
DRY_RUN_FILE_CHANGES = []


def set_dry_run(enabled):
  """Enables or disables dry-run mode for this module.

  Dry-run mode redirects all DB updates and file writes into the
  in-memory DRY_RUN_DB_CHANGES / DRY_RUN_FILE_CHANGES buffers so the
  caller can report what *would* happen without touching MongoDB or
  the filesystem.

  Args:
    enabled (bool): True to enable dry-run capture; False to restore
      normal write behaviour and clear the buffers.
  """
  global DRY_RUN
  DRY_RUN = bool(enabled)
  DRY_RUN_DB_CHANGES.clear()
  DRY_RUN_FILE_CHANGES.clear()


def _write_file(target, content):
  """Writes `content` to `target`, honouring dry-run mode.

  In dry-run mode the intended change is appended to
  DRY_RUN_FILE_CHANGES with a minimal diff summary and the file is
  not touched.  Otherwise the file is overwritten with `content`.

  Args:
    target (str): Absolute path of the file.
    content (str): Full file content to write.
  """
  if DRY_RUN:
    existed = os.path.exists(target)
    if existed:
      with open(target, 'r') as file_handle:
        before = file_handle.read()
    else:
      before = ''
    if before == content:
      return
    before_lines = before.splitlines()
    after_lines = content.splitlines()
    DRY_RUN_FILE_CHANGES.append({
      'path': target,
      'created': not existed,
      'lines_before': len(before_lines),
      'lines_after': len(after_lines),
      'delta': len(after_lines) - len(before_lines)})
    return
  with open(target, 'w') as file_handle:
    file_handle.write(content)

_REPO_ROOT = os.environ.get('NUTEST_PATH') or os.path.abspath(
  os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
SKILL_DIR = os.path.join(
  _REPO_ROOT, '.cursor', 'skills', 'triage-cdp-test-failure')
PATTERNS_FILE = os.path.join(
  SKILL_DIR, 'failure-patterns-reference.md')
FLOWS_DIR = os.path.join(SKILL_DIR, 'flows')
README_FILE = os.path.join(SKILL_DIR, 'README.md')
SOURCEGRAPH_FILE = os.path.join(SKILL_DIR, 'sourcegraph-reference.md')
INVESTIGATE_FILE = os.path.join(
  SKILL_DIR, 'investigate-reference.md')
GENERIC_PATTERNS_HEADER = '## Generic Cross-Cutting Patterns'
COMPONENT_MAPPING_HEADER = '## Common Repo-to-Component Mapping'


def is_valid_flow_name(name):
  """Checks whether an investigation_flow value is usable.

  A flow_used record must reference a real flow section name.
  Values like 'unknown', 'none', empty string, or None indicate
  the skill failed to set the field.

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


def format_operation_flow(raw_flow):
  """Formats an operation flow string into a readable multi-line
  form.

  Splits on ' -> ' arrows and indents each step. If the flow is
  already multi-line, returns it as-is.

  Args:
    raw_flow (str): Raw operation flow string from the DB.

  Returns:
    str: Formatted operation flow.
  """
  if '\n' in raw_flow:
    return raw_flow

  steps = [s.strip() for s in raw_flow.split('->')]
  if len(steps) <= 1:
    return raw_flow

  lines = [steps[0]]
  for step in steps[1:]:
    indent = '  ' * min(len(lines), 6)
    lines.append(f"{indent}-> {step}")
  return '\n'.join(lines)


def normalize_for_dedup(text):
  """Strips punctuation and collapses whitespace for fuzzy
  comparison.

  Args:
    text (str): Raw text to normalize.

  Returns:
    str: Lowercased, punctuation-stripped, whitespace-collapsed
      string.
  """
  return re.sub(
    r'\s+', ' ', re.sub(r'[^\w\s]', '', text.lower())).strip()


def is_duplicate_step(candidate, existing_steps):
  """Checks whether a candidate step is a semantic duplicate.

  Uses normalized substring overlap: if either the candidate is a
  substring of an existing step or vice versa (after
  normalization), it's treated as a duplicate.

  Args:
    candidate (str): New triage step text.
    existing_steps (list): List of already-collected triage step
      texts.

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
  """Heuristic: does the text look like a grep command or
  pattern?

  Distinguishes actual grep/regex patterns from prose triage
  steps that happen to mention log file names.

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


def normalize_dependency(dep):
  """Normalizes a service dependency dict to a hashable string
  key.

  Args:
    dep (dict): Dict with 'from', 'to', and 'context' keys.

  Returns:
    str: Normalized key like 'curator -> idf: stats lookup',
      or empty string if invalid.
  """
  if not isinstance(dep, dict):
    return ''
  from_svc = dep.get('from', '').strip().lower()
  to_svc = dep.get('to', '').strip().lower()
  context = dep.get('context', '').strip()
  if not from_svc or not to_svc:
    return ''
  return f"{from_svc} -> {to_svc}: {context}"


def item_meets_threshold(item_info, threshold):
  """Checks if an enrichment item meets the promotion threshold.

  User-guided items are promoted immediately. Skill-generated
  items need `threshold` unique test runs.

  Args:
    item_info (dict): Dict with 'sessions', 'test_runs',
      'has_user_guided'.
    threshold (int): Minimum unique test runs for
      skill-generated items.

  Returns:
    bool: True if the item is ready for promotion.
  """
  if item_info.get('has_user_guided', False):
    return True
  return (
    len(item_info.get('test_runs', set())) >= threshold)


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
    extra_fields (dict): Optional dict of additional fields to
      set.
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

  Sets promotion_status to 'promoted' with a promoted_at
  timestamp and the flow_id they were promoted to.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    cluster (list): List of encounter documents to mark.
    flow_id (str): The flow_id they were promoted to.
  """
  doc_ids = [str(enc.get('_id', '')) for enc in cluster
             if enc.get('_id')]
  update_promotion_status(db, doc_ids, 'promoted', {
    'promoted_at': int(time.time()),
    'promoted_flow_id': flow_id})


def mark_enrichments_promoted(db, mature_enrichments):
  """Marks flow_used documents as promoted after enrichment
  apply.

  Collects all doc_ids from mature enrichment items and sets
  their promotion_status to 'promoted'.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    mature_enrichments (dict): Output of
      get_mature_enrichments().
  """
  doc_ids = set()
  for categories in mature_enrichments.values():
    for items in categories.values():
      for info in items.values():
        doc_ids.update(info.get('doc_ids', set()))

  if doc_ids:
    update_promotion_status(db, list(doc_ids), 'promoted', {
      'promoted_at': int(time.time())})


def mark_awaiting_manual_apply(db, mature_enrichments):
  """Marks flow_used documents whose enrichments still need
  manual application.

  Used when the curator has identified mature enrichments but has
  no automation path to apply them to the flow section (e.g.
  free-text `triage_steps`, `new_failure_modes`, or
  `new_cross_service_checks` additions). The status stays in
  PROMOTABLE_STATUSES so the enrichments resurface on the next
  run until an operator applies them and re-runs the curator.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    mature_enrichments (dict): Output of
      get_mature_enrichments().
  """
  doc_ids = set()
  for categories in mature_enrichments.values():
    for items in categories.values():
      for info in items.values():
        doc_ids.update(info.get('doc_ids', set()))

  if doc_ids:
    update_promotion_status(db, list(doc_ids),
                            'awaiting_manual_apply', {
      'last_surfaced_at': int(time.time())})


def mark_no_enrichment(db, flow_used_encounters):
  """Marks flow_used documents that have no enrichment data.

  These are flow_used entries with flow_enrichment=None that
  have promotable status. They are tracked for usage stats but
  have nothing to promote.

  Args:
    db (MongoDBClient): Connected MongoDBClient instance.
    flow_used_encounters (list): List of flow_used encounter
      documents.
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
    flow_used_encounters (list): List of flow_used encounter
      documents.
    mature_enrichments (dict): Output of
      get_mature_enrichments().
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


# -------------------------------------------------------------------
# File I/O helpers
# -------------------------------------------------------------------

def _normalize_flow_id(heading):
  """Converts a flow heading into a normalized ID for
  comparison.

  Args:
    heading (str): Raw heading text from markdown.

  Returns:
    str: Lowercased, non-alphanumeric chars replaced with '_'.
  """
  return re.sub(r'[^a-z0-9]+', '_', heading.lower()).strip('_')


def get_existing_flow_ids(flows_dir=None):
  """Reads existing flow section headings from all flow files.

  Scans every .md file in the flows directory for ## and ###
  headings.

  Args:
    flows_dir (str): Path to the flows directory. Defaults to
      FLOWS_DIR.

  Returns:
    set: Normalized flow heading IDs.
  """
  target_dir = flows_dir or FLOWS_DIR
  if not os.path.isdir(target_dir):
    return set()

  ids = set()
  for filename in os.listdir(target_dir):
    if not filename.endswith('.md'):
      continue
    filepath = os.path.join(target_dir, filename)
    with open(filepath, 'r') as file_handle:
      content = file_handle.read()
    headings = re.findall(r'^###?\s+(.+)$', content, re.MULTILINE)
    ids.update(_normalize_flow_id(heading) for heading in headings)
  return ids


def parse_flow_directory(patterns_file=None):
  """Reads the Flow Directory table from the index file.

  Parses the markdown table under '## Flow Directory' and
  returns a mapping of normalized flow ID to relative file path.

  Args:
    patterns_file (str): Path to the index file. Defaults to
      PATTERNS_FILE.

  Returns:
    dict: Mapping of normalized flow ID to file path relative
      to SKILL_DIR.
  """
  target = patterns_file or PATTERNS_FILE
  if not os.path.exists(target):
    return {}

  with open(target, 'r') as file_handle:
    content = file_handle.read()

  directory = {}
  in_table = False
  header_passed = False
  for line in content.split('\n'):
    stripped = line.strip()
    if stripped == '## Flow Directory':
      in_table = True
      continue
    if in_table and stripped.startswith('##'):
      break
    if not in_table:
      continue

    if stripped.startswith('|') and '---' in stripped:
      header_passed = True
      continue
    if not header_passed:
      continue
    if not stripped.startswith('|'):
      if stripped and not stripped.startswith('---'):
        break
      continue

    cells = [c.strip() for c in stripped.split('|')]
    cells = [c for c in cells if c]
    if len(cells) < 2:
      continue

    flow_name = cells[0]
    link_match = re.search(
      r'\[.*?\]\((.+?)\)', cells[1])
    if link_match:
      rel_path = link_match.group(1)
    else:
      rel_path = cells[1]

    directory[_normalize_flow_id(flow_name)] = rel_path

  return directory


def get_flow_file_for_name(flow_name, patterns_file=None):
  """Looks up which flow file contains a given flow section.

  Args:
    flow_name (str): The investigation flow name as stored in
      DB.
    patterns_file (str): Path to the index file. Defaults to
      PATTERNS_FILE.

  Returns:
    str: Absolute path to the flow file, or None if not found.
  """
  directory = parse_flow_directory(patterns_file)
  normalized = _normalize_flow_id(flow_name)

  rel_path = directory.get(normalized)
  if rel_path:
    skill_dir = os.path.dirname(patterns_file or PATTERNS_FILE)
    return os.path.join(skill_dir, rel_path)

  return None


_DOMAIN_SKIP_WORDS = {
  'the', 'a', 'an', 'and', 'or', 'for', 'of', 'in', 'on', 'to',
  'with', 'from', 'by', 'at', 'is', 'pc', 'pe', 'investigation',
  'flow', 'flows', 'check'}


def _first_significant_word(flow_name):
  """Returns the first significant alphabetic word in a flow
  name.

  Used by both the domain-filename derivation and the first-
  title derivation so both agree on the primary identifier. Keeps
  the original casing so acronyms like 'AHV' or 'PE' remain
  upper-cased when used in titles.

  Args:
    flow_name (str): Raw flow name (any casing).

  Returns:
    str: Significant word preserving original casing, or empty
      string if none.
  """
  for word in re.findall(r'[A-Za-z]+', flow_name):
    if word.lower() not in _DOMAIN_SKIP_WORDS and len(word) > 2:
      return word
  return ''


def _derive_domain_filename(flow_name):
  """Derives a domain flow filename from a proposed flow name.

  Extracts the first significant word (typically the primary
  service) from the flow name and uses it as the domain.

  Args:
    flow_name (str): Proposed flow name from telemetry.

  Returns:
    str: Filename like 'cerebro-flows.md'.
  """
  significant = _first_significant_word(flow_name)
  domain = significant.lower() if significant else 'general'
  return f"{domain}-flows.md"


def _update_flow_directory(flow_name, rel_path,
                           patterns_file=None):
  """Adds an entry to the Flow Directory table in the index.

  Args:
    flow_name (str): Human-readable flow name.
    rel_path (str): Relative path from skill dir.
    patterns_file (str): Path to the index file. Defaults to
      PATTERNS_FILE.
  """
  target = patterns_file or PATTERNS_FILE
  with open(target, 'r') as file_handle:
    content = file_handle.read()

  new_row = f"| {flow_name} | [{rel_path}]({rel_path}) |"

  separator = '\n---\n'
  dir_header = '## Flow Directory'
  dir_idx = content.find(dir_header)
  if dir_idx >= 0:
    next_sep = content.find(separator, dir_idx)
    if next_sep < 0:
      insert_pos = len(content)
    else:
      insert_pos = next_sep

    insert_text = new_row + '\n'
    content = content[:insert_pos] + insert_text + content[insert_pos:]

    _write_file(target, content)


def append_flow_to_file(section, flow_name=None,
                        flows_dir=None,
                        patterns_file=None):
  """Appends a new flow section to the appropriate flow file.

  Determines the target file from the flow_name. If the flow
  name matches an existing domain file, appends there. Otherwise
  creates a new domain file. Also updates the Flow Directory
  table in the index file.

  Args:
    section (str): Markdown section string to insert.
    flow_name (str): Human-readable flow name for directory
      lookup and domain derivation. If None, falls back to
      'general-flows.md'.
    flows_dir (str): Path to the flows directory. Defaults to
      FLOWS_DIR.
    patterns_file (str): Path to the index file. Defaults to
      PATTERNS_FILE.
  """
  target_dir = flows_dir or FLOWS_DIR
  index_file = patterns_file or PATTERNS_FILE
  os.makedirs(target_dir, exist_ok=True)

  target_file = None
  if flow_name:
    target_file = get_flow_file_for_name(flow_name, index_file)

  if not target_file:
    if flow_name:
      domain_filename = _derive_domain_filename(flow_name)
    else:
      domain_filename = 'general-flows.md'
    target_file = os.path.join(target_dir, domain_filename)

  if os.path.exists(target_file):
    with open(target_file, 'r') as file_handle:
      content = file_handle.read()
    content = content.rstrip('\n') + '\n\n---\n\n' + section
  else:
    title = _first_significant_word(flow_name or '') or 'General'
    if title.islower():
      title = title.capitalize()
    content = f"# {title} Investigation Flows\n\n" + section

  _write_file(target_file, content)

  if flow_name:
    rel_path = os.path.relpath(target_file,
                               os.path.dirname(index_file))
    _update_flow_directory(flow_name, rel_path, index_file)

  update_readme_flow_table(target_dir)


def update_readme_flow_table(flows_dir=None,
                             readme_file=None):
  """Regenerates the Flow Files table in the README.

  Scans every .md file in the flows directory, extracts the
  domain title and flow section headings, counts lines, and
  rewrites the ``### Flow Files`` table in the README.

  Args:
    flows_dir (str): Path to the flows directory. Defaults
      to FLOWS_DIR.
    readme_file (str): Path to the README. Defaults to
      README_FILE.
  """
  target_dir = flows_dir or FLOWS_DIR
  readme = readme_file or README_FILE

  if os.path.isdir(target_dir) and os.path.exists(readme):
    rows = _build_flow_table_rows(target_dir)
    if rows:
      _replace_flow_table_in_readme(rows, readme)


def _build_flow_table_rows(flows_dir):
  """Builds markdown table rows from flow files on disk.

  Args:
    flows_dir (str): Path to the flows directory.

  Returns:
    list: Markdown table row strings, one per flow file.
  """
  rows = []
  for filename in sorted(os.listdir(flows_dir)):
    if not filename.endswith('.md'):
      continue
    filepath = os.path.join(flows_dir, filename)
    with open(filepath, 'r') as file_handle:
      content = file_handle.read()

    line_count = content.count('\n')
    if content and not content.endswith('\n'):
      line_count += 1

    flow_headings = re.findall(r'^###\s+(.+)$', content, re.MULTILINE)
    flows_desc = '; '.join(flow_headings) if flow_headings else '\u2014'

    rows.append(f"| `{filename}` | ~{line_count} | {flows_desc} |")
  return rows


def _replace_flow_table_in_readme(rows, readme):
  """Replaces the Flow Files table in the README.

  Args:
    rows (list): Markdown table row strings.
    readme (str): Path to the README file.
  """
  new_table = ("### Flow Files (`flows/`)\n\n| File | Lines | Flows |\n"
               "|---|---|---|\n" + '\n'.join(rows) + '\n')

  with open(readme, 'r') as file_handle:
    content = file_handle.read()

  table_start = content.find('### Flow Files')
  if table_start >= 0:
    heading_match = re.search(r'\n#{1,6}\s+\S', content[table_start + 1:])
    if heading_match is None:
      table_end = len(content)
    else:
      table_end = table_start + 1 + heading_match.start() + 1

    content = content[:table_start] + new_table + content[table_end:]

    _write_file(readme, content)


# -------------------------------------------------------------------
# ServiceDependencyMap
# -------------------------------------------------------------------

_TRIAGE_HEADER = '**How to use during triage:**'
_EXT_STORAGE_HEADER = (
  '**External storage additional dependencies:**')
_DEP_MAP_HEADER = '## Service Dependency Map'


class ServiceDependencyMap:
  """Parses and appends to the Service Dependency Map section in
  failure-patterns-reference.md.

  Uses an append-only strategy: existing hand-crafted content is
  preserved verbatim, and new edges are appended at the end of
  the appropriate sub-section. The ASCII diagram is never touched.
  """

  def __init__(self):
    """Initializes an empty ServiceDependencyMap."""
    self._existing_edges = set()
    self._ascii_diagram = ''
    self._triage_end_pos = -1
    self._ext_end_pos = -1
    self._section_found = False

  def parse(self, content):
    """Extracts existing edges from the dependency map section.

    Scans the triage and external-storage bullet sections to
    build a set of known (from, to) edges, and records the
    character positions where new bullets should be appended.

    Args:
      content (str): Full file content.

    Returns:
      bool: True if the section was found and parsed.
    """
    if _DEP_MAP_HEADER not in content:
      return False

    self._section_found = True
    section_start = content.index(_DEP_MAP_HEADER)

    diagram_start = content.find('```\n', section_start)
    diagram_end = content.find('\n```\n', diagram_start + 4)
    if diagram_start >= 0 and diagram_end >= 0:
      self._ascii_diagram = content[diagram_start + 4:diagram_end]

    self._extract_edges(content, section_start)
    self._find_insert_positions(content, section_start)

    return True

  def get_existing_edges(self):
    """Returns all edges found in the bullet sections.

    Returns:
      set: Set of (from_service, to_service) tuples,
        lowercased.
    """
    return set(self._existing_edges)

  def add_dependencies(self, content, new_deps):
    """Appends new dependency bullets to the file content.

    Preserves all existing content verbatim. New non-external-
    storage edges are appended to the triage section; new
    external-storage edges to the ext-storage section.

    Args:
      content (str): Full file content.
      new_deps (list): List of dicts with 'from', 'to',
        'context' keys.

    Returns:
      tuple: (updated_content, added_list) where added_list is
        a list of (from, to, context) tuples that were
        inserted.
    """
    if not self._section_found:
      return content, []

    existing = set(self._existing_edges)
    triage_bullets = []
    ext_bullets = []
    added = []

    ext_storage_keywords = {'external', 'powerstore', 'pure', 'nvme',
                            'array', 'externalstorageinterface'}

    for dep in new_deps:
      from_svc = dep.get('from', '').strip()
      to_svc = dep.get('to', '').strip()
      context = dep.get('context', '').strip()
      if not from_svc or not to_svc:
        continue

      edge = (from_svc.lower(), to_svc.lower())
      if edge in existing:
        continue

      combined_lower = f"{from_svc} {to_svc} {context}".lower()
      is_ext = any(kw in combined_lower for kw in ext_storage_keywords)

      if is_ext:
        ext_bullets.append(f"- `{from_svc.lower()}` → "
                           f"`{to_svc.lower()}` ({context})")
      else:
        triage_bullets.append(f"- `{from_svc.lower()}` fatal → check "
                              f"`{to_svc.lower()}`")

      existing.add(edge)
      added.append((from_svc, to_svc, context))

    if not added:
      return content, []

    if ext_bullets and self._ext_end_pos >= 0:
      insert_text = '\n'.join(ext_bullets) + '\n'
      content = (content[:self._ext_end_pos] + insert_text
                 + content[self._ext_end_pos:])
      shift = len(insert_text)
    else:
      shift = 0

    if triage_bullets and self._triage_end_pos >= 0:
      pos = self._triage_end_pos
      if self._ext_end_pos >= 0 and pos > self._ext_end_pos:
        pos += shift
      insert_text = '\n'.join(triage_bullets) + '\n'
      content = content[:pos] + insert_text + content[pos:]

    return content, added

  def validate_diagram(self):
    """Checks for edges in bullets but missing from ASCII
    diagram.

    Returns:
      list: List of (from, to) tuples missing from the diagram.
    """
    if not self._ascii_diagram:
      return []

    diagram_lower = self._ascii_diagram.lower()
    missing = []

    for from_svc, to_svc in self._existing_edges:
      if (from_svc not in diagram_lower or to_svc not in diagram_lower):
        missing.append((from_svc, to_svc))

    return missing

  def _extract_edges(self, content, section_start):
    """Scans bullets to extract existing (from, to) edges.

    Parses two patterns from the dependency map bullets:
    1. Triage: `svc` fatal -> check `dep1`, `dep2`
    2. Ext storage: `svc` -> `target` (context)

    Hand-written bullets may wrap across multiple lines; continuation
    lines (no leading '- ') are stitched onto the preceding bullet
    before matching so the edge regex sees the full text.

    Args:
      content (str): Full file content.
      section_start (int): Character position of the section
        header.
    """
    self._existing_edges = set()
    next_section = content.find('\n---\n', section_start + 1)
    if next_section < 0:
      next_section = len(content)
    section_text = content[section_start:next_section]

    bullets = []
    current = None
    for line in section_text.split('\n'):
      stripped = line.strip()
      if stripped.startswith('- '):
        if current is not None:
          bullets.append(current)
        current = stripped
      elif current is not None and stripped and not stripped.startswith('#'):
        current = f"{current} {stripped}"
      else:
        if current is not None:
          bullets.append(current)
          current = None
    if current is not None:
      bullets.append(current)

    # Allow multi-word service names like "stargate vdiskcontroller"
    # inside the backticks (used by ext-storage bullets).
    name_pattern = r'[\w\s-]+?'
    check_pattern = (
      rf'^-\s+`({name_pattern})`\s+.*?→\s*check\s+(.*)')
    arrow_pattern = (
      rf'^-\s+`({name_pattern})`\s*→\s*`({name_pattern})`')

    for stripped in bullets:
      check_match = re.match(check_pattern, stripped)
      if check_match:
        from_svc = check_match.group(1).strip().lower()
        targets = re.findall(
          rf'`({name_pattern})`', check_match.group(2))
        for target in targets:
          self._existing_edges.add((from_svc, target.strip().lower()))
        continue

      arrow_match = re.match(arrow_pattern, stripped)
      if arrow_match:
        self._existing_edges.add(
          (arrow_match.group(1).strip().lower(),
           arrow_match.group(2).strip().lower()))
        continue

      prose_match = re.match(
        r'^-\s+(?!`).+?→\s*check\s+(.*)', stripped)
      if prose_match:
        targets = re.findall(
          rf'`({name_pattern})`', prose_match.group(1))
        for idx in range(len(targets) - 1):
          self._existing_edges.add(
            (targets[idx].strip().lower(),
             targets[idx + 1].strip().lower()))

  def _find_insert_positions(self, content, section_start):
    """Finds where to insert new bullets in each sub-section.

    Locates the last bullet line before the next blank line or
    header in each sub-section.

    Args:
      content (str): Full file content.
      section_start (int): Character position of the section
        header.
    """
    self._triage_end_pos = -1
    self._ext_end_pos = -1

    triage_idx = content.find(_TRIAGE_HEADER, section_start)
    if triage_idx >= 0:
      self._triage_end_pos = self._find_last_bullet_end(
        content, triage_idx + len(_TRIAGE_HEADER))

    ext_idx = content.find(_EXT_STORAGE_HEADER, section_start)
    if ext_idx >= 0:
      self._ext_end_pos = self._find_last_bullet_end(
        content, ext_idx + len(_EXT_STORAGE_HEADER))

  def _find_last_bullet_end(self, content, start):
    """Finds the end position of the last bullet in a
    sub-section.

    Returns the position immediately after the last non-blank
    line in the bullet block (including continuation lines).

    Args:
      content (str): Full file content.
      start (int): Position to start scanning from.

    Returns:
      int: Character position after the last bullet line.
    """
    lines = content[start:].split('\n')
    pos = start
    last_content_end = start

    for line in lines:
      stripped = line.strip()
      if stripped.startswith('**'):
        break
      if stripped.startswith('##') or stripped == '---':
        break

      pos += len(line) + 1

      if stripped.startswith('- ') or (
          stripped and not line[0:1].strip()):
        last_content_end = pos

    return last_content_end


# -------------------------------------------------------------------
# Skill update applicators (ASCII diagrams, component mappings,
# generic cross-cutting patterns)
# -------------------------------------------------------------------

def _slug(text):
  """Normalizes text to a slug for dedup comparison.

  Args:
    text (str): Raw text.

  Returns:
    str: Lowercased alphanumeric slug.
  """
  return re.sub(r'[^a-z0-9]+', '_', (text or '').lower()).strip('_')


def apply_ascii_diagram_patches(patches, patterns_file=None):
  """Appends titled sub-diagrams to the Service Dependency Map.

  Each patch is a dict with keys:
    - `subsystem_header` (str, required): bold markdown header
      used both for the rendered subsection label and for dedup
      (e.g. '**Management / UI plane (cluster classification):**')
    - `diagram` (str, required): ASCII block (no surrounding
      triple-backtick fences; fences are added by this helper)
    - `description` (str, optional): informational string, not
      rendered in the file (lives in telemetry for operators)

  Insertion is idempotent on `subsystem_header`. New sub-diagrams
  are placed after any existing bold sub-sections but before the
  `**How to use during triage:**` bullets, if present.

  Args:
    patches (list): List of patch dicts.
    patterns_file (str): Path override. Defaults to
      PATTERNS_FILE.

  Returns:
    list: Subset of `patches` that were actually inserted.
  """
  target = patterns_file or PATTERNS_FILE
  if not patches or not os.path.exists(target):
    return []

  with open(target, 'r') as file_handle:
    content = file_handle.read()

  if _DEP_MAP_HEADER not in content:
    return []

  applied = []
  triage_header_idx = content.find(_TRIAGE_HEADER)
  if triage_header_idx < 0:
    section_start = content.index(_DEP_MAP_HEADER)
    next_sep = content.find('\n---\n', section_start)
    insert_pos = next_sep if next_sep >= 0 else len(content)
  else:
    insert_pos = triage_header_idx

  pieces = []
  for patch in patches:
    header = patch.get('subsystem_header', '').strip()
    diagram = patch.get('diagram', '').rstrip('\n')
    if not header or not diagram:
      continue
    if header in content:
      continue
    block = f"{header}\n\n```\n{diagram}\n```\n\n"
    pieces.append(block)
    applied.append(patch)

  if not pieces:
    return []

  content = (content[:insert_pos] + ''.join(pieces)
             + content[insert_pos:])

  _write_file(target, content)

  return applied


def apply_component_mappings(mappings, sourcegraph_file=None):
  """Appends rows to the Component Mapping table.

  Each mapping dict has keys:
    - `component` (str, required): first-column label
    - `repo` (str, required): repo name or short label
    - `local_path` (str, optional): xgear / ~/main path
    - `sourcegraph_path` (str, optional): Sourcegraph repo path

  Idempotent on the `component` label.

  Args:
    mappings (list): List of mapping dicts.
    sourcegraph_file (str): Path override. Defaults to
      SOURCEGRAPH_FILE.

  Returns:
    list: Subset of `mappings` that were appended.
  """
  target = sourcegraph_file or SOURCEGRAPH_FILE
  if not mappings or not os.path.exists(target):
    return []

  with open(target, 'r') as file_handle:
    content = file_handle.read()

  if COMPONENT_MAPPING_HEADER not in content:
    return []

  section_start = content.index(COMPONENT_MAPPING_HEADER)
  next_sep = content.find('\n---\n', section_start)
  section_end = next_sep if next_sep >= 0 else len(content)
  section_text = content[section_start:section_end]
  existing_components = {
    m.group(1).strip().lower()
    for m in re.finditer(
      r'^\|\s*([^|]+?)\s*\|', section_text, re.MULTILINE)}

  new_rows = []
  applied = []
  for mapping in mappings:
    component = mapping.get('component', '').strip()
    if not component or component.lower() in existing_components:
      continue
    repo = mapping.get('repo', '').strip() or '\u2014'
    local_path = mapping.get('local_path', '').strip() or '\u2014'
    sg_path = mapping.get('sourcegraph_path', '').strip() or '\u2014'
    new_rows.append(f"| {component} | {repo} | {local_path} | {sg_path} |")
    applied.append(mapping)
    existing_components.add(component.lower())

  if not new_rows:
    return []

  table_end_match = re.search(r'(\n\|[^\n]+\|\s*\n)(?=\n)',
                              section_text)
  if table_end_match is None:
    return []
  insert_abs = section_start + table_end_match.end() - 1
  insertion = '\n'.join(new_rows) + '\n'
  content = (content[:insert_abs] + insertion
             + content[insert_abs:])

  _write_file(target, content)

  return applied


def apply_generic_patterns(patterns, investigate_file=None):
  """Appends generic cross-cutting pattern subsections.

  Each pattern dict has keys:
    - `title` (str, required): rendered as `### <title>`
    - `body` (str, required): pre-formatted markdown body
      (paragraphs, bullets, code blocks). No wrapping is applied.

  If the host file has no `## Generic Cross-Cutting Patterns`
  section, a new one is appended at end of file.

  Idempotent on `title`.

  Args:
    patterns (list): List of pattern dicts.
    investigate_file (str): Path override. Defaults to
      INVESTIGATE_FILE.

  Returns:
    list: Subset of `patterns` that were appended.
  """
  target = investigate_file or INVESTIGATE_FILE
  if not patterns or not os.path.exists(target):
    return []

  with open(target, 'r') as file_handle:
    content = file_handle.read()

  if GENERIC_PATTERNS_HEADER not in content:
    content = (content.rstrip('\n') + '\n\n'
               f"{GENERIC_PATTERNS_HEADER}\n\n"
               "These heuristics apply across multiple flows.\n")

  section_start = content.index(GENERIC_PATTERNS_HEADER)
  next_section_match = re.search(r'\n##\s', content[section_start + 1:])
  if next_section_match is None:
    section_end = len(content)
  else:
    section_end = section_start + 1 + next_section_match.start()
  section_text = content[section_start:section_end]

  existing_titles = {
    _slug(match.group(1))
    for match in re.finditer(
      r'^###\s+(.+)$', section_text, re.MULTILINE)}

  new_blocks = []
  applied = []
  for pattern in patterns:
    title = pattern.get('title', '').strip()
    body = pattern.get('body', '').rstrip('\n')
    if not title or not body:
      continue
    if _slug(title) in existing_titles:
      continue
    new_blocks.append(f"### {title}\n\n{body}\n")
    applied.append(pattern)
    existing_titles.add(_slug(title))

  if not new_blocks:
    return []

  insertion = '\n'.join(new_blocks) + '\n'
  trimmed = content[:section_end].rstrip('\n')
  content = trimmed + '\n\n' + insertion + content[section_end:]

  _write_file(target, content)

  return applied
