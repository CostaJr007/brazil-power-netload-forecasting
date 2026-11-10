"""Verificações locais dos leitores meteorológicos, sem consultar a internet."""
import tempfile
from pathlib import Path

import eccodes

# Carregamos o módulo pela pasta scripts sem iniciar o comando principal.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "preparacao"))
from discover_weather import Links
from download_weather import grib_inventory


def test_directory_parser_keeps_links_without_running_scripts():
    """O parser só coleta href; não executa código que venha no HTML."""
    parser = Links()
    parser.feed('<a href="rain.grib2">rain</a><script>throw new Error()</script><a>sem URL</a>')
    assert parser.urls == ["rain.grib2"]


def test_grib_inventory_retains_level_and_reference_metadata():
    """Uma mensagem sintética comprova decodificação e preservação de metadados."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "sample.grib2"
        handle = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
        try:
            with path.open("wb") as output:
                eccodes.codes_write(handle, output)
        finally:
            eccodes.codes_release(handle)
        messages = grib_inventory(path)
        assert len(messages) == 1
        assert messages[0]["numberOfDataPoints"] > 0
        assert messages[0]["typeOfLevel"] is not None
        assert len(messages[0]["bbox_wgs84"]) == 4
