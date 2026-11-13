"""Processing contracts and idempotency; every example is local."""
import json
import sys
import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pipeline import Pipeline, select_recent
from silver import build_silver, ons_frame, inmet_frames


def manifest(path):
    return {"source": "ons", "dataset": "test", "resource_id": "r", "path": str(path),
            "sha256": "abc", "ingested_at": "2026-11-10T12:00:00+00:00", "url": "https://example.org/data.parquet"}


def test_period_selection_crosses_year_and_includes_next_day():
    resources = [{"url": f"https://example.org/DATA_{day}.parquet", "id": day,
                  "format": "PARQUET"} for day in ["2025_12_31", "2026_01_01", "2026_01_02", "2024_01_01", "1999_01_01"]]
    found = select_recent(resources, date(2026, 1, 1), 2)
    assert {r["id"] for r in found} == {"2025_12_31", "2026_01_01", "2026_01_02"}


def test_ons_normalization_quarantine_and_sin_are_explicit(tmp_path):
    path = tmp_path / "source.parquet"
    pl.DataFrame({"id_subsistema": ["N ", "SIN", "SE"], "din_instante": ["2026-11-09"] * 3,
                  "val_carga": ["1,5", "2.0", "oops"]}).write_parquet(path)
    contract = {"required": ["id_subsistema", "din_instante", "val_carga"],
                "numeric": ["val_carga"], "event_column": "din_instante"}
    before = path.read_bytes()
    valid, rejected, _ = ons_frame(path, manifest(path), contract)
    assert valid["id_subsistema"].to_list() == ["N", "SIN"]
    assert valid["val_carga"].to_list() == [1.5, 2.0]
    assert valid["_is_sin_aggregate"].to_list() == [False, True]
    assert rejected.height == 1
    assert path.read_bytes() == before


def test_same_input_reuses_published_snapshot(tmp_path):
    path = tmp_path / "source.parquet"
    pl.DataFrame({"id_subsistema": ["N "], "val_carga": [1.0]}).write_parquet(path)
    contract = {"required": ["id_subsistema", "val_carga"], "numeric": ["val_carga"]}
    first = build_silver(tmp_path, manifest(path), contract, "v1", [-60, -30, -40, 0])
    second = build_silver(tmp_path, manifest(path), contract, "v1", [-60, -30, -40, 0])
    assert first == second
    assert len(list((tmp_path / "silver").rglob("*.valid.parquet"))) == 1
    assert first["status"] == "published"


def test_ear_above_nominal_range_is_flagged_without_clipping(tmp_path):
    path = tmp_path / "ear.parquet"
    pl.DataFrame({"ear_verif_bacia_percentual": [130.6]}).write_parquet(path)
    valid, rejected, _ = ons_frame(path, manifest(path), {"numeric": ["ear_verif_bacia_percentual"]})
    assert rejected.height == 0
    assert valid["ear_verif_bacia_percentual"][0] == 130.6
    assert valid["_quality_warnings"][0].to_list() == ["outside_nominal_range:ear_verif_bacia_percentual"]


def test_inmet_parse_sentinel_and_units_before_renaming(tmp_path):
    path = tmp_path / "station.zip"
    text = "REGIAO:;CO\nUF:;DF\nESTACAO:;TESTE\nCODIGO (WMO):;A001\nLATITUDE:;-15,7\nLONGITUDE:;-47,9\nALTITUDE:;1000\nDATA DE FUNDACAO:;2000\n"
    text += "Data;Hora UTC;PRECIPITAÇÃO TOTAL, HORÁRIO (mm);UMIDADE RELATIVA DO AR, HORARIA (%);\n"
    text += "2026/11/09;0000 UTC;1,5;75;\n2026/11/09;0100 UTC;-9999;200;\n"
    with ZipFile(path, "w") as archive:
        archive.writestr("station.csv", text.encode("latin-1"))
    meta = {**manifest(path), "source": "inmet", "dataset": "automatic_stations_annual"}
    _, valid, rejected, stats = next(inmet_frames(path, meta))
    assert valid["precipitation_mm"][0] == 1.5
    assert rejected.height == 1
    assert rejected["precipitation_mm"][0] is None
    assert stats["missing_measurements"]["precipitation_mm"] == 1


def test_http_validator_reuses_existing_bytes(tmp_path, monkeypatch):
    """An identical HEAD must not trigger a GET or duplicate the acquisition."""
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    meta = {**manifest(source), "sha256": hashlib.sha256(b"original").hexdigest(),
            "headers": {"ETag": '"v1"', "Content-Length": "8"}}
    job = Pipeline(tmp_path, {"version": "test", "scheduler_minutes": 15, "blocked_sources": {}}, {})
    class Response:
        headers = meta["headers"]
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr("pipeline.urlopen", lambda *args, **kwargs: Response())
    monkeypatch.setattr(job, "previous_manifest", lambda url: (job.fingerprint(meta["headers"]), meta))
    def forbidden(*args, **kwargs):
        raise AssertionError("GET should not happen")
    monkeypatch.setattr(job.store, "fetch", forbidden)
    try:
        assert job.obtain("ons", "test", "r", meta["url"]) == meta
    finally:
        job.close()


def test_failed_task_does_not_postpone_retry_or_block_other_source(tmp_path):
    """A failure does not record a last success; independent sources keep running."""
    job = Pipeline(tmp_path, {"version": "test", "scheduler_minutes": 15, "blocked_sources": {}}, {})
    def fail():
        raise ValueError("falha simulada")
    try:
        job.task("bad", 60, fail)
        assert job.due("bad", 60)
        job.task("good", 60, lambda: None)
        assert not job.due("good", 60)
        assert len(job.report["errors"]) == 1
    finally:
        job.close()
