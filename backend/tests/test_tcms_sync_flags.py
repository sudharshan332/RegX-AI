"""Unit tests for JITA TCMS sync flags applied on JP create/clone."""

import os
import textwrap
import unittest


# Product values JITA puts on `service` / SUT.product for different JP types.
PRODUCT_SERVICES = ("PC", "AOS", "NOS", "AWS", "Files", "NC2", "Calm", "pc", "aos")


def _load_tcms_helpers():
    path = os.path.join(os.path.dirname(__file__), "..", "test_flask.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("        def _set_tcms_sync_flags(")
    end = src.index("        def _apply_retain_setup_on_failure(")
    ns = {}
    exec(textwrap.dedent(src[start:end]), ns)  # noqa: S102
    return ns


class TestSetTcmsSyncFlags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep helpers in a dict so unittest does not bind them as methods.
        cls.ns = _load_tcms_helpers()

    def _apply(self, payload, enabled, sync_branch=None):
        self.ns["_set_tcms_sync_flags"](payload, enabled, sync_branch)
        return payload

    def test_enabled_overwrites_every_product_service(self):
        for product in PRODUCT_SERVICES:
            with self.subTest(product=product):
                payload = {
                    "service": product,
                    "services": [product],
                    "package_type": "tar",
                    "test_service": "NutestPy3Tests",
                    "system_under_test": {
                        "product": product.lower(),
                        "branch": "master",
                    },
                }
                self._apply(payload, True)
                self.assertEqual(payload["service"], "nutest-py3test")
                # Product identity on the JP must stay (only TCMS service changes).
                self.assertEqual(payload["services"], [product])
                self.assertEqual(payload["system_under_test"]["product"], product.lower())

    def test_enabled_sets_service_when_missing(self):
        payload = {}
        self._apply(payload, True)
        self.assertEqual(payload["service"], "nutest-py3test")
        self.assertEqual(payload["package_type"], "tar")
        self.assertEqual(payload["test_service"], "NutestPy3Tests")

    def test_enabled_overwrites_empty_and_whitespace_service(self):
        for raw in ("", "   ", None):
            with self.subTest(raw=raw):
                payload = {"service": raw}
                self._apply(payload, True)
                self.assertEqual(payload["service"], "nutest-py3test")

    def test_enabled_is_idempotent(self):
        payload = {"service": "nutest-py3test"}
        self._apply(payload, True)
        self._apply(payload, True)
        self.assertEqual(payload["service"], "nutest-py3test")

    def test_jita_get_after_post_restores_product_then_put_fixes_it(self):
        """Clone/create POST can be ignored by JITA; GET returns the product service."""
        for product in ("PC", "AOS", "NOS", "AWS"):
            with self.subTest(product=product):
                posted = {"service": product, "system_under_test": {"product": product.lower()}}
                self._apply(posted, True)
                self.assertEqual(posted["service"], "nutest-py3test")

                # JITA GET after POST echoes the product again (observed for PC).
                fetched = {
                    "service": product,
                    "package_type": "",
                    "test_service": "",
                    "tester_tags": ["official"],
                    "system_under_test": {"product": product.lower(), "branch": "ganges-stable"},
                }
                self._apply(fetched, True)
                self.assertEqual(fetched["service"], "nutest-py3test")
                self.assertEqual(fetched["package_type"], "tar")
                self.assertEqual(fetched["test_service"], "NutestPy3Tests")
                self.assertEqual(fetched["system_under_test"]["product"], product.lower())

    def test_empty_package_and_test_service_are_filled(self):
        payload = {"service": "AWS", "package_type": "  ", "test_service": None}
        self._apply(payload, True)
        self.assertEqual(payload["package_type"], "tar")
        self.assertEqual(payload["test_service"], "NutestPy3Tests")

    def test_explicit_package_and_test_service_are_kept(self):
        payload = {"service": "NOS", "package_type": "iso", "test_service": "CustomTest"}
        self._apply(payload, True)
        self.assertEqual(payload["service"], "nutest-py3test")
        self.assertEqual(payload["package_type"], "iso")
        self.assertEqual(payload["test_service"], "CustomTest")

    def test_disabled_clears_tcms_fields_for_any_product(self):
        for product in ("PC", "AOS", "AWS"):
            with self.subTest(product=product):
                payload = {
                    "service": product,
                    "package_type": "tar",
                    "test_service": "NutestPy3Tests",
                    "tester_tags": ["official", "cdp"],
                    "services": [product],
                }
                self._apply(payload, False)
                self.assertEqual(payload["service"], "")
                self.assertEqual(payload["package_type"], "")
                self.assertEqual(payload["test_service"], "")
                self.assertEqual(payload["tester_tags"], ["cdp"])
                self.assertEqual(payload["services"], [product])

    def test_non_dict_payload_is_a_no_op(self):
        self._apply(None, True)
        self._apply("PC", True)

    def test_sync_branch_does_not_change_service_rule(self):
        payload = {
            "service": "AWS",
            "system_under_test": {"product": "aws", "branch": "old"},
        }
        self._apply(payload, True, sync_branch="ganges-7.6-stable")
        self.assertEqual(payload["service"], "nutest-py3test")
        self.assertEqual(payload["system_under_test"]["product"], "aws")
        self.assertEqual(payload["system_under_test"]["branch"], "ganges-7.6-stable")


class TestForceTcmsServiceOnTestSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_tcms_helpers()

    def _apply(self, payload):
        self.ns["_force_tcms_service_on_test_set"](payload)
        return payload

    def test_fresh_ts_sets_service_on_payload_and_rows(self):
        payload = {
            "name": "NEW_TS",
            "tests": [
                {"name": "pkg.Test.a", "service": "PC", "package_type": ""},
                {"name": "pkg.Test.b", "service": "AOS"},
                {"name": "pkg.Test.c"},
            ],
        }
        self._apply(payload)
        self.assertEqual(payload["service"], "nutest-py3test")
        self.assertEqual(payload["package_type"], "tar")
        for row in payload["tests"]:
            self.assertEqual(row["service"], "nutest-py3test")
            self.assertEqual(row["package_type"], "tar")

    def test_cloned_ts_overwrites_product_service(self):
        for product in ("PC", "AOS", "NOS", "AWS"):
            with self.subTest(product=product):
                payload = {
                    "service": product,
                    "package_type": "tar",
                    "tests": [{"name": "t1", "service": product, "package_type": "tar"}],
                }
                self._apply(payload)
                self.assertEqual(payload["service"], "nutest-py3test")
                self.assertEqual(payload["tests"][0]["service"], "nutest-py3test")
                self.assertEqual(payload["package_type"], "tar")

    def test_non_dict_is_a_no_op(self):
        self._apply(None)
        self._apply("ts")
