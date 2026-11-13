"""Local checks of the weather readers, without using the network."""
import tempfile
from pathlib import Path

import eccodes

# Load the module from the scripts folder without starting its main command.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "preparacao"))
from discover_weather import Links
from download_weather import grib_inventory


def test_directory_parser_keeps_links_without_running_scripts():
    """The parser only collects href; it never runs code coming in the HTML."""
    parser = Links()
    parser.feed('<a href="rain.grib2">rain</a><script>throw new Error()</script><a>no URL</a>')
    assert parser.urls == ["rain.grib2"]


def test_grib_inventory_retains_level_and_reference_metadata():
    """A synthetic message proves decoding and metadata preservation."""
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
