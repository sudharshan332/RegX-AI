"""Tests for CVM installer node-fatal RDM pattern matching."""

import json
import os
import re
import unittest


PATTERN_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "CDP_FT",
    "rdm_failure_patterns.json",
)

SAMPLE_MESSAGE = """Installer errors:

Nodes: kylun01-1: Received "fatal" in waiting for event "Running CVM Installer": An exception was raised: Traceback (most recent call last):
"""

MULTI_NODE_INSTALLER_MESSAGE = """Installer errors:

Nodes: pitpf06-4: The target node is not in a valid cluster (imaged by fnd)

pitpf07-2: The target node is not in a valid cluster (imaged by fnd)

pitpf10-3: The target node is not in a valid cluster (imaged by fnd)

pitpf05-2: The target node is not in a valid cluster (imaged by fnd)
"""

MULTI_NODE_NAMES = ["pitpf06-4", "pitpf07-2", "pitpf10-3", "pitpf05-2"]

NODE_EXTRACT_PATTERNS = [
    r'([\w-]+):\s*Received\s+"fatal"\s+in\s+waiting\s+for\s+event',
    r"(?:Nodes?:\s*)([a-zA-Z][\w\-]*\d+[-\d]*)",
]


def _load_extract_helpers():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("def _extract_installer_error_nodes(")
    if "_INSTALLER_NODE_LINE_RE" in src[:start]:
        start = src.rfind("_INSTALLER_NODE_LINE_RE = re.compile(", 0, start)
    end = src.index("\ndef _ticket_keys_from_rdm_skill(")
    ns = {"re": re}
    exec(src[start:end], ns)  # noqa: S102
    return ns


class TestCvmInstallerNodePattern(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PATTERN_FILE, "r") as f:
            cls.patterns = json.load(f).get("patterns", [])

    def _find(self, pattern_id):
        for p in self.patterns:
            if p.get("id") == pattern_id:
                return p
        self.fail(f"Pattern {pattern_id} not found")

    def test_cvm_installer_pattern_matches_kylun_failure(self):
        pattern = self._find("cvm_installer_node_fatal")
        compiled = re.compile(pattern["regex"], re.IGNORECASE | re.DOTALL)
        match = compiled.search(SAMPLE_MESSAGE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "kylun01-1")
        self.assertEqual(pattern["category"], "INFRA_NODE")
        self.assertEqual(pattern["next_action"], "disable_node_and_rerun")
        self.assertIn("Rerun cause due to node issue", pattern["comment_template"])
        self.assertIn("{node_name}", pattern["comment_template"])

    def test_installer_node_failure_fallback_also_matches(self):
        pattern = self._find("installer_node_failure")
        compiled = re.compile(pattern["regex"], re.IGNORECASE | re.DOTALL)
        match = compiled.search(SAMPLE_MESSAGE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "kylun01-1")

    def test_specific_pattern_is_listed_before_generic_installer(self):
        ids = [p["id"] for p in self.patterns]
        self.assertLess(
            ids.index("cvm_installer_node_fatal"),
            ids.index("installer_node_failure"),
        )

    def test_extract_node_name_from_installer_message(self):
        seen = {}
        for regex in NODE_EXTRACT_PATTERNS:
            for name in re.findall(regex, SAMPLE_MESSAGE):
                seen.setdefault(name, None)
        self.assertIn("kylun01-1", seen)

    def test_comment_template_renders_disable_and_rerun_cause(self):
        pattern = self._find("cvm_installer_node_fatal")
        comment = pattern["comment_template"].replace("{node_name}", "kylun01-1")
        self.assertEqual(
            comment,
            "regx_rerun_disable-kylun01-1 Rerun cause due to node issue",
        )

    def test_extract_all_nodes_from_multi_node_installer_errors(self):
        extract = _load_extract_helpers()["_extract_node_names"]
        nodes = extract(MULTI_NODE_INSTALLER_MESSAGE)
        self.assertEqual(nodes, MULTI_NODE_NAMES)

    def test_multi_node_comment_includes_every_installer_node(self):
        pattern = self._find("installer_node_failure")
        extract = _load_extract_helpers()["_extract_node_names"]
        nodes = extract(MULTI_NODE_INSTALLER_MESSAGE)
        comment = ", ".join(
            pattern["comment_template"].replace("{node_name}", n) for n in nodes
        )
        self.assertEqual(nodes, MULTI_NODE_NAMES)
        for name in MULTI_NODE_NAMES:
            self.assertIn("regx_rerun_disable-%s" % name, comment)
        self.assertIn("Rerun cause due to node issue", comment)

    def test_extract_keeps_single_installer_node(self):
        extract = _load_extract_helpers()["_extract_node_names"]
        self.assertEqual(extract(SAMPLE_MESSAGE), ["kylun01-1"])

    def test_patterns_file_is_valid_json(self):
        with open(PATTERN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data.get("patterns"), list)
        self.assertGreater(len(data["patterns"]), 0)


class TestRdmPatternsCommentTolerance(unittest.TestCase):
    def test_strips_js_line_comments(self):
        path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("def _strip_json_line_comments(")
        end = src.index("\ndef _read_rdm_patterns_json(")
        ns = {}
        exec(src[start:end], ns)  # noqa: S102
        text = '{\n  "patterns": [\n    // {\n    //   "id": "disabled"\n    // },\n    {"id": "keep"}\n  ]\n}\n'
        parsed = json.loads(ns["_strip_json_line_comments"](text))
        self.assertEqual(parsed["patterns"], [{"id": "keep"}])


if __name__ == "__main__":
    unittest.main()
