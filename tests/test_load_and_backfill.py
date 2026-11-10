"""Testes da API de carga, backfill, trava e detecção de páginas de bloqueio. Sem rede."""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import acquire  # noqa: E402
import pipeline as pipeline_module  # noqa: E402
from backfill import months  # noqa: E402
from pipeline import LockBusy, Pipeline, file_period, select_period, single_run  # noqa: E402
from silver import load_frame  # noqa: E402

CONFIG = {"version": "test", "scheduler_minutes": 15, "blocked_sources": {}, "max_invalid_fraction": 0.01,
          "ons_load": {"programada_areas": ["SECO"], "programada_offsets": [0, 1],
                       "verificada_areas": ["SECO"], "verificada_lookback_days": 2,
                       "contracts": {"carga-energia-programada": {"required": ["cod_areacarga", "din_referenciautc"]}}}}


def load_manifest(path, area="SECO", day="2026-11-08"):
    return {"source": "ons", "dataset": "carga-energia-programada", "resource_id": f"programada_{area}_{day}",
            "path": str(path), "sha256": "x" + area + day, "ingested_at": "2026-11-10T12:00:00+00:00",
            "url": "https://apicarga.ons.org.br/prd/cargaprogramada?cod_areacarga=" + area,
            "context": {"api": "apicarga"}}


def test_file_period_and_history_selection():
    assert file_period("https://x/CMO_SEMANAL_2026.parquet") == (date(2026, 1, 1), date(2026, 12, 31))
    assert file_period("https://x/GER_2024_02.parquet") == (date(2024, 2, 1), date(2024, 2, 29))
    assert file_period("https://x/RESERVATORIO.parquet") is None
    resources = [{"url": f"https://x/D_{y}.parquet", "format": "PARQUET"} for y in (2016, 2018, 2026)]
    resources.append({"url": "https://x/CADASTRO.parquet", "format": "PARQUET"})
    found = select_period(resources, date(2018, 1, 1), date(2025, 12, 31), include_undated=False)
    assert [r["url"] for r in found] == ["https://x/D_2018.parquet"]


def test_months_split_partial_edges():
    assert list(months(date(2025, 12, 20), date(2026, 2, 3))) == [
        (date(2025, 12, 20), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 1, 31)), (date(2026, 2, 1), date(2026, 2, 3))]


def test_load_frame_declares_utc_interval_and_rejects_duplicates(tmp_path):
    rows = [{"cod_areacarga": "SECO ", "dat_referencia": "2026-11-08", "din_referenciautc": "2026-11-08T03:30:00.000Z",
             "val_cargaglobalprogramada": 41213.53},
            {"cod_areacarga": "SECO", "dat_referencia": "2026-11-08", "din_referenciautc": "2026-11-08T04:00:00.000Z",
             "val_cargaglobalprogramada": "abc"},
            {"cod_areacarga": "S", "dat_referencia": "2026-11-08", "din_referenciautc": "2026-11-08T04:00:00.000Z",
             "val_cargaglobalprogramada": 1.0},
            {"cod_areacarga": "S", "dat_referencia": "2026-11-08", "din_referenciautc": "2026-11-08T04:00:00.000Z",
             "val_cargaglobalprogramada": 2.0}]
    path = tmp_path / "load.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    valid, rejected, stats = load_frame(path, load_manifest(path), {"required": ["cod_areacarga", "din_referenciautc"]})
    assert valid.height == 1 and rejected.height == 3
    row = valid.row(0, named=True)
    assert row["cod_areacarga"] == "SECO"
    # Fim do intervalo é o valor da fonte; início = fim - 30 min, ambos em UTC.
    assert row["interval_end_utc"] == datetime(2026, 11, 8, 3, 30, tzinfo=timezone.utc)
    assert row["interval_start_utc"] == datetime(2026, 11, 8, 3, 0, tzinfo=timezone.utc)
    reasons = sorted(r for errs in rejected["_quality_errors"].to_list() for r in errs)
    assert reasons == ["duplicate_key", "duplicate_key", "invalid_numeric:val_cargaglobalprogramada"]


def test_zero_total_load_is_flagged_not_dropped(tmp_path):
    """A área SIN da API publica zeros; o valor fica, com alerta explícito."""
    path = tmp_path / "sin.json"
    path.write_text(json.dumps([{"cod_areacarga": "SIN", "din_referenciautc": "2026-11-08T03:30:00.000Z",
                                 "val_cargaglobal": 0}]), encoding="utf-8")
    valid, rejected, stats = load_frame(path, load_manifest(path), {})
    assert valid.height == 1 and rejected.height == 0
    assert valid["_quality_warnings"][0].to_list() == ["zero_total_load"]
    assert stats["warning_rows"] == 1


def test_load_frame_rejects_empty_payload(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="vazia"):
        load_frame(path, load_manifest(path), {})


def test_load_slots_do_not_collide_between_areas(tmp_path):
    """URLs da API têm o mesmo caminho; cada área/dia precisa do próprio slot no índice atual."""
    job = Pipeline(tmp_path, CONFIG, {})
    try:
        for area in ("SECO", "S"):
            path = tmp_path / f"{area}.json"
            path.write_text(json.dumps([{"cod_areacarga": area, "din_referenciautc": "2026-11-08T03:30:00.000Z",
                                         "val_cargaglobalprogramada": 1.0}]), encoding="utf-8")
            job.transform(load_manifest(path, area))
        identities = [r[0] for r in job.state.execute("SELECT identity FROM snapshots")]
        assert len(identities) == 2
    finally:
        job.close()


def test_empty_load_at_publication_edge_is_not_an_error(tmp_path, monkeypatch):
    job = Pipeline(tmp_path, CONFIG, {})
    calls = []

    def fake_fetch(kind, area, start, end, resource_id, role):
        calls.append(start)
        today = datetime.now(timezone(timedelta(hours=-3))).date()
        # Amanhã ainda não publicado; hoje publicado.
        rows = [] if start > today else [{"cod_areacarga": area}]
        return {"dataset": "carga-energia-" + kind}, rows

    monkeypatch.setattr(job, "fetch_load", fake_fetch)
    monkeypatch.setattr(job, "transform", lambda manifest: None)
    try:
        job.ons_load("programada")
        assert len(calls) == 2
        assert job.report["errors"] == []
    finally:
        job.close()


def test_empty_load_outside_edge_is_an_error(tmp_path, monkeypatch):
    job = Pipeline(tmp_path, CONFIG, {})
    monkeypatch.setattr(job, "fetch_load", lambda *a: ({}, []))
    try:
        job.ons_load("verificada")
        # D-1 é borda (pode não ter saído); D-2 vazio é problema.
        assert len(job.report["errors"]) == 1
        assert "verificada" in job.report["errors"][0]["task"]
    finally:
        job.close()


def test_previous_manifest_uses_latest_acquisition(tmp_path):
    folder = tmp_path / "bronze" / "ons" / "d" / "r"
    folder.mkdir(parents=True)
    for stamp in ("2026-11-01T00:00:00+00:00", "2026-11-09T00:00:00+00:00"):
        payload = folder / stamp[:10]
        payload.write_bytes(b"x")
        (folder / (stamp[:10] + ".manifest.json")).write_text(json.dumps(
            {"url": "https://x/f.parquet", "path": str(payload), "ingested_at": stamp, "headers": {}}), encoding="utf-8")
    job = Pipeline(tmp_path, CONFIG, {})
    try:
        _, item = job.previous_manifest("https://x/f.parquet")
        assert item["ingested_at"].startswith("2026-11-09")
    finally:
        job.close()


def test_resolve_data_path_rebases_moved_data_folder(tmp_path, monkeypatch):
    """Manifesto gravado com caminho de outro disco continua encontrando o arquivo."""
    new_root = tmp_path / "novo_disco" / "data"
    target = new_root / "bronze" / "ons" / "x" / "abc"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"1")
    monkeypatch.setattr(acquire, "DATA_DIR", new_root)
    old = r"C:\Users\alguem\Energy\data\bronze\ons\x\abc"
    assert acquire.resolve_data_path(old) == target
    assert acquire.resolve_data_path(str(target)) == target
    assert str(acquire.resolve_data_path(r"C:\nada\aqui.txt")).endswith("aqui.txt")


def test_lock_busy_is_reported_distinctly(tmp_path):
    lock = tmp_path / "x.lock"
    with single_run(lock):
        with pytest.raises(LockBusy):
            with single_run(lock):
                pass


class Response(BytesIO):
    def __init__(self, content, content_type):
        super().__init__(content)
        self.headers = {"Content-Length": str(len(content)), "Content-Type": content_type}

    def geturl(self):
        return "https://example.org/x"


@pytest.mark.parametrize("body,ctype", [
    (b'<meta charset="UTF-8"><title>Acesso bloqueado</title>', "application/octet-stream"),
    (b'{"looks": "like json"}', "text/html; charset=utf-8")])
def test_block_pages_are_not_saved_as_data(tmp_path, monkeypatch, body, ctype):
    store = acquire.Store(tmp_path)
    monkeypatch.setattr(acquire, "open_http", lambda url: Response(body, ctype))
    try:
        with pytest.raises(ValueError, match="HTML"):
            store.fetch("ccee", "pld", "r", "https://example.org/x")
        assert not [p for p in (tmp_path / "bronze").rglob("*") if p.is_file()]
    finally:
        store.close()
