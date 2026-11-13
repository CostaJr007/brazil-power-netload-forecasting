# No real servers: unittest.mock.patch replaces the network function during each test.
# Each test checks one property: revision, failures, CSV preservation or resource selection.

import importlib.util
import json
# Importa tempfile: cria pastas de teste removidas ao sair do contexto.
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("acquire", Path(__file__).resolve().parents[1] / "scripts/acquire.py")
acquire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acquire)


# Response: a BytesIO subclass that simulates an HTTP response held in memory.
class Response(BytesIO):
    def __init__(self, content):
        super().__init__(content)
        # Simulated Content-Length: the size the server would declare for the body.
        self.headers = {"Content-Length": str(len(content))}

    def geturl(self):
        return "https://example.org/data.csv"


class AcquisitionTests(unittest.TestCase):
    # Two identical contents and one revision: the first object is reused and both distinct versions are kept.
    def test_identical_content_reuses_object_and_revision_preserves_both(self):
        with tempfile.TemporaryDirectory() as folder:
            store = acquire.Store(folder)
            try:
                items = []
                for content in [b"id;value\n1;2\n", b"id;value\n1;2\n", b"id;value\n1;3\n"]:
                    # Within this block, open_http is replaced by the simulated response and restored on exit.
                    with patch.object(acquire, "open_http", return_value=Response(content)):
                        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
                        items.append(store.fetch("ons", "x", "r", "https://example.org/data.csv"))
                # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
                self.assertEqual(items[1]["status"], "unchanged")
                # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
                self.assertEqual(items[0]["path"], items[1]["path"])
                # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
                self.assertNotEqual(items[0]["path"], items[2]["path"])
                # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
                self.assertTrue(Path(items[0]["path"]).exists())
                # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
                self.assertEqual(store.db.execute("select count(*) from attempts").fetchone()[0], 3)
            finally:
                store.close()

    # An unexpected HTML page and an oversized file: errors are recorded and temporary files removed.
    def test_html_and_size_failure_recorded_without_partial_objects(self):
        with tempfile.TemporaryDirectory() as folder:
            store = acquire.Store(folder)
            try:
                for content, limit in [(b"<html>error</html>", 100), (b"123456", 2)]:
                    # Within this block, open_http is replaced by the simulated response and restored on exit.
                    with patch.object(acquire, "open_http", return_value=Response(content)):
                        with self.assertRaises(ValueError):
                            store.fetch("ons", "x", "r", "https://example.org/data.csv", limit)
                # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
                self.assertEqual(store.db.execute("select count(*) from attempts where status='error'").fetchone()[0], 2)
                # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
                self.assertEqual(list(Path(folder).rglob("*.part")), [])
            finally:
                store.close()

    # Synthetic CSV with a repeated key, an empty cell and a decimal comma: metrics are right and bytes are unchanged.
    def test_profile_preserves_strings_and_detects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.csv"
            path.write_text("id;value\n01;2,5\n01;\n02;-3\n", encoding="utf-8")
            before = path.read_bytes()
            report = acquire.profile_csv(path, ["id"])
            # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
            self.assertEqual(report["duplicate_keys"], 1)
            # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
            self.assertEqual(report["empty_cells"]["value"], 1)
            # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
            self.assertEqual(path.read_bytes(), before)

    # Fake catalog with a dictionary, a Swagger page and a CSV: filters return only the requested resource type.
    def test_plan_does_not_confuse_dictionary_api_and_dataset(self):
        catalog = {"packages": [{"name": "x", "resources": [
            {"id": "d", "name": "Dicionário de Dados", "format": "JSON", "url": "https://example.org/d.json"},
            {"id": "a", "name": "API", "format": "API", "url": "https://example.org/swagger"},
            {"id": "r", "name": "2025 CSV", "format": "CSV", "url": "https://example.org/2025.csv"}]}]}
        result = acquire.resource_plan(catalog, ["x"], "CSV", "2025", False)
        # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
        self.assertEqual([r["resource_id"] for r in result], ["r"])
        result = acquire.resource_plan(catalog, ["x"], "JSON", "", True)
        # Verifica a expectativa do teste; se o resultado divergir, unittest registra falha neste ponto.
        self.assertEqual([r["resource_id"] for r in result], ["d"])


if __name__ == "__main__":
    unittest.main()
