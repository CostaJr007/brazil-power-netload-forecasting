"""Inspeciona o lote meteorológico local e publica um resumo de aquisição.

Não baixa dados, não corrige valores e não calcula previsões ou médias por bacia.
"""
import json
import re
from pathlib import Path

# pypdf lê a documentação técnica; ecCodes já inspecionou os arquivos GRIB.
from pypdf import PdfReader

from acquire import DATA_DIR, ROOT, atomic_json, utcnow


def main():
    """Relaciona os arquivos recebidos a metadados, limitações e documentação."""
    report_path = ROOT / "docs/inventory/weather_acquisition.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    files = report["files"]
    manual = next(f for f in files if f["dataset"] == "merge_documentation" and f["url"].endswith(".pdf"))
    # O texto extraído é auxiliar para leitura; o PDF original permanece na Bronze.
    reader = PdfReader(manual["manifest"]["path"])
    pages = [page.extract_text() or "" for page in reader.pages]
    documentation = DATA_DIR / "weather_documentation"
    documentation.mkdir(parents=True, exist_ok=True)
    (documentation / "merge_manual.txt").write_text("\n\n".join(pages), encoding="utf-8")
    # Registramos páginas com termos importantes para revisão humana dos intervalos.
    relevant = [{"page": i + 1, "text": text} for i, text in enumerate(pages)
                if re.search(r"12.?UTC|12.?GMT|12.?Z|acumul|24 horas|estaç", text, re.I)]
    atomic_json(documentation / "merge_manual_relevant_pages.json", relevant)
    for page in relevant:
        # O console recebe só um trecho; o texto completo está salvo localmente.
        print(f"MANUAL página {page['page']}: {page['text'][:2000]}")

    rows = []
    for item in files:
        messages = item.get("messages", [])
        if item["dataset"] == "merge_daily":
            for message in messages:
                # O CTL do produto declara dois campos: PREC e NEST. Os nomes
                # genéricos do ecCodes são preservados e não usados como definição.
                if message["shortName"] == "rdp":
                    message["product_field_from_ctl"] = "PREC"
                    message["product_description_from_ctl"] = "Surface Precipitation [kg/m^2]"
                elif message["shortName"] == "prmsl":
                    message["product_field_from_ctl"] = "NEST"
                    message["product_description_from_ctl"] = "Number of Stations / Grid Point"
        if item["dataset"] == "gfs_0p25":
            # Checamos os campos realmente recebidos para os componentes de vento.
            available = {(m["shortName"], m["typeOfLevel"], m["level"]) for m in messages}
            required = {("u", "heightAboveGround", 100), ("v", "heightAboveGround", 100),
                        ("10u", "heightAboveGround", 10), ("10v", "heightAboveGround", 10),
                        ("2t", "heightAboveGround", 2)}
            item["required_fields_missing"] = [list(k) for k in sorted(required - available)]
            if item["required_fields_missing"]:
                raise ValueError("GFS sem todos os campos essenciais pedidos")
        rows.append({"source": item["source"], "dataset": item["dataset"], "url": item["url"],
                     "validation": item["validation_status"], "bytes": item.get("manifest", {}).get("bytes"),
                     "sha256": item.get("manifest", {}).get("sha256"), "grib_messages": len(messages)})
    summary = {"checked_at": utcnow(), "files": len(files),
               "total_bytes": sum(r["bytes"] or 0 for r in rows),
               "errors": report["errors"], "resources": rows,
               "invalid_source_basins": [b for b in report["basin_quality"] if not b["source_geometry_valid"]]}
    report["summary"] = summary
    atomic_json(report_path, report)
    atomic_json(ROOT / "docs/inventory/weather_summary.json", summary)
    # O resumo usa as referências efetivamente recebidas, não datas fixas no script.
    merge_files = [f for f in files if f["dataset"] == "merge_daily"]
    merge_dates = sorted(f["manifest"]["context"]["file_reference"] for f in merge_files)
    gfs_files = [f for f in files if f["dataset"] == "gfs_0p25"]
    gfs_context = gfs_files[0]["manifest"]["context"] if gfs_files else {}
    inmet_files = [f for f in files if f["source"] == "inmet"]
    station = inmet_files[0].get("station_inventory", {}) if inmet_files else {}
    sample = station.get("sample_observations") or {}
    invalid = summary["invalid_source_basins"]
    lines = ["# Meteorologia: dados efetivamente adquiridos", "",
             f"Verificação UTC: {summary['checked_at']}. Arquivos: {len(files)}. Bytes originais: {summary['total_bytes']:,}.", "",
             "| Origem | Produto | Arquivo/consulta | Situação |", "|---|---|---|---|"]
    for item in files:
        lines.append(f"| {item['source']} | {item['dataset']} | [fonte]({item['url']}) | {item['validation_status']} |")
    lines += ["", "## Conteúdo e escopo", "",
              f"- MERGE: {len(merge_files)} arquivos diários, referências {merge_dates}, grade original 0,1°, com CTL e manual. O CTL declara PREC (precipitação) e NEST (número de estações por ponto); a rotulagem genérica rdp/prmsl não define a natureza do produto. Metadados originais preservados.",
              f"- GFS: rodada {gfs_context.get('run_date')}, ciclo {gfs_context.get('cycle_utc')} UTC; {len(gfs_files)} arquivos para horizontes 24/48/72 h. Grade 0,25°, retângulo das bacias com margem. Componentes de vento a 10/100 m e temperatura a 2 m conferidos; há pressão, precipitação e radiação.",
              f"- INMET: {station.get('csv_members')} membros CSV; {station.get('stations_read')} cadastros lidos. Membro amostrado: {sample.get('member')}; referências {sample.get('min_reference_text')} a {sample.get('max_reference_text')}. Não certifica cobertura uniforme das demais estações.",
              f"- Geografia: {len(report['basin_quality'])} feições ONS; {len(invalid)} geometrias inválidas. Vínculo candidato de {station.get('stations_intersecting_valid_basins')} estações com bacias válidas. As inválidas foram excluídas só da consulta espacial; fonte original preservada.",
              "- Manual MERGE de 26/05/2025: documenta a nova base baseada em IMERG V07B e histórico reprocessado desde 1998. A mesma nomenclatura de arquivo não garante a mesma versão do processamento. A convenção precisa do fechamento diário permanece para confirmação antes de agregar por dia civil.",
              "", "## Limites para a próxima etapa", "",
              "O lote é inicial. Os três horizontes GFS são instantes espaçados, não uma previsão horária contínua. O recorte das bacias não garante cobertura de todos os parques eólicos/solares; a localização dos ativos será um cadastro separado.",
              "A precipitação GFS contém mensagens com diferentes startStep/endStep: selecionar uma mensagem por intervalo antes de somar. Unidades foram preservadas, incluindo Kelvin, Pa, kg/m², m/s e W/m². Radiação média em W/m² não é diretamente a radiação acumulada em kJ/m² publicada pelo INMET.",
              "Não foram calculadas médias de chuva por bacia, reparadas geometrias, preenchidas lacunas ou removidos valores. A Silver permanece uma fase posterior. ERA5/CDS, GEFS, ECMWF e ANA ainda não têm aquisição executada nesta entrega.",
              "", "## Reproduzir", "", "```powershell",
              ".\\.venv\\Scripts\\python.exe scripts/discover_weather.py",
              ".\\.venv\\Scripts\\python.exe scripts/download_weather.py",
              ".\\.venv\\Scripts\\python.exe scripts/report_weather.py", "```", "",
              "As listagens oficiais foram preservadas em data/weather_catalog. Os originais meteorológicos estão em data/bronze/inpe, data/bronze/noaa e data/bronze/inmet, com manifestos e histórico SQLite."]
    (ROOT / "docs/inventory/weather_acquisition.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"files": summary["files"], "bytes": summary["total_bytes"], "errors": summary["errors"]}))


if __name__ == "__main__":
    main()
