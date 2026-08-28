"""Analyze, Fix & Re-run must POST one parent-task /rerun for selected tests."""
import os
import unittest


PARENT = "6a882ccc8e79ced6155e02f2"
CHILD_A = "6a9120a7b5e475bf60fef92b"
CHILD_B = "6a9120a68e79ceade871e2bf"

QOS_SNAPSHOT = (
    "cdp.stargate.qos_policy.vm_throttling.test_qos_policy."
    "TestQOSPolicy.test_policy_advance___snapshot"
)
QOS_DISK = (
    "cdp.stargate.qos_policy.vm_throttling.test_qos_policy."
    "TestQOSPolicy.test_policy_crud___disk_add_remove_esx"
)


def _load_helpers():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("def _jita_oid_str(")
    end = src.index("\ndef _rerun_selected_tests(")
    ns = {}
    exec(src[start:end], ns)  # noqa: S102
    return ns


class TestRdmAutoWorkflowRerunGrouping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_helpers()

    def test_explicit_parent_wins(self):
        tests = [
            {"agave_task_id": CHILD_A, "testcase_name": QOS_SNAPSHOT, "testcase_id": "id1"},
            {"agave_task_id": CHILD_B, "testcase_name": QOS_DISK, "testcase_id": "id2"},
        ]
        parent = self.ns["_resolve_rerun_parent_task_id"](tests, PARENT)
        self.assertEqual(parent, PARENT)

    def test_shared_task_id_is_parent(self):
        tests = [
            {"agave_task_id": PARENT, "testcase_name": QOS_SNAPSHOT, "testcase_id": "id1"},
            {"agave_task_id": PARENT, "testcase_name": QOS_DISK, "testcase_id": "id2"},
        ]
        parent = self.ns["_resolve_rerun_parent_task_id"](tests)
        self.assertEqual(parent, PARENT)

    def test_majority_task_id_when_mixed(self):
        tests = [
            {"agave_task_id": PARENT, "testcase_name": QOS_SNAPSHOT, "testcase_id": "id1"},
            {"agave_task_id": PARENT, "testcase_name": QOS_DISK, "testcase_id": "id2"},
            {"agave_task_id": CHILD_A, "testcase_name": "other", "testcase_id": "id3"},
        ]
        parent = self.ns["_resolve_rerun_parent_task_id"](tests)
        self.assertEqual(parent, PARENT)

    def test_group_without_parent_keeps_per_task_buckets(self):
        tests = [
            {"agave_task_id": CHILD_A, "testcase_name": QOS_SNAPSHOT, "testcase_id": "id1"},
            {"agave_task_id": CHILD_B, "testcase_name": QOS_DISK, "testcase_id": "id2"},
        ]
        grouped = self.ns["_group_tests_for_rerun"](tests)
        self.assertEqual(set(grouped), {CHILD_A, CHILD_B})
        self.assertEqual(len(grouped[CHILD_A]), 1)
        self.assertEqual(len(grouped[CHILD_B]), 1)

    def test_group_with_parent_is_single_rerun(self):
        tests = [
            {"agave_task_id": CHILD_A, "testcase_name": QOS_SNAPSHOT, "testcase_id": "id1"},
            {"agave_task_id": CHILD_B, "testcase_name": QOS_DISK, "testcase_id": "id2"},
        ]
        grouped = self.ns["_group_tests_for_rerun"](tests, parent_task_id=PARENT)
        self.assertEqual(list(grouped.keys()), [PARENT])
        self.assertEqual(len(grouped[PARENT]), 2)
        names = {item["name"] for item in grouped[PARENT]}
        self.assertEqual(names, {QOS_SNAPSHOT, QOS_DISK})
        ids = {item["test_result_id"] for item in grouped[PARENT]}
        self.assertEqual(ids, {"id1", "id2"})

    def test_group_accepts_oid_dicts(self):
        tests = [
            {
                "agave_task_id": {"$oid": CHILD_A},
                "testcase_name": QOS_SNAPSHOT,
                "testcase_id": "id1",
            },
            {
                "agave_task_id": {"$oid": CHILD_B},
                "testcase_name": QOS_DISK,
                "test_result_id": "id2",
            },
        ]
        parent = self.ns["_resolve_rerun_parent_task_id"](tests, {"$oid": PARENT})
        grouped = self.ns["_group_tests_for_rerun"](tests, parent_task_id=parent)
        self.assertEqual(list(grouped.keys()), [PARENT])
        self.assertEqual(len(grouped[PARENT]), 2)


if __name__ == "__main__":
    unittest.main()
