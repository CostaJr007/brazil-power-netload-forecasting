r"""Generates the Power BI project as text in bi/: semantic model (TMDL) and, with --relatorio, the report pages (PBIR).

Why generate by code: tables, types, relationships and DAX measures are versioned in git and rebuilt identically
whenever a column changes. Measures on hourly tables default to the national grid when no subsystem is selected.

Run: .\.venv\Scripts\python.exe scripts/gerar_projeto_bi.py [--relatorio]   (after scripts/exportar_bi.py)
--relatorio regenerates the 5 pages (scripts/relatorio_bi.py), overwriting edits made in Power BI Desktop.
"""
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import DATA_DIR  # noqa: E402
from relatorio_bi import escrever_pbir  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
BI = RAIZ / "bi"
MODELO = BI / "Energia.SemanticModel"
RELATORIO = BI / "Energia.Report"
T = "\t"

DATAS = {"date", "decision_date"}
TIPOS = {"int64": "int64", "int32": "int64", "double": "double", "float": "double", "bool": "boolean", "string": "string",
         "large_string": "string"}

# Measures per table: name -> (DAX, format). One line each, to keep TMDL simple.
ERRO = "ABS({t}[forecast] - {t}[actual])"
NL = "fact_net_load"
MEDIDAS = {
    NL: {
        "Model MAE (MW)": (f"AVERAGEX({NL}, " + ERRO.format(t=NL) + ")", "#,0"),
        "Benchmark MAE (MW)": (f"AVERAGEX({NL}, ABS({NL}[benchmark] - {NL}[actual]))", "#,0"),
        "ONS schedule MAE (MW)": (f"AVERAGEX(FILTER({NL}, NOT ISBLANK({NL}[ons_schedule])), ABS({NL}[ons_schedule] - {NL}[actual]))", "#,0"),
        "Error reduction vs benchmark": ("DIVIDE([Benchmark MAE (MW)] - [Model MAE (MW)], [Benchmark MAE (MW)])", "0.0%"),
        "Model bias (MW)": (f"AVERAGEX({NL}, {NL}[forecast] - {NL}[actual])", "#,0"),
        "MAPE model": (f"AVERAGEX(FILTER({NL}, {NL}[actual] <> 0), " + ERRO.format(t=NL) + f" / ABS({NL}[actual]))", "0.00%"),
        "Actual (MW)": (f"AVERAGE({NL}[actual])", "#,0"),
        "Forecast (MW)": (f"AVERAGE({NL}[forecast])", "#,0"),
        "Benchmark (MW)": (f"AVERAGE({NL}[benchmark])", "#,0"),
        "Band 80% low": (f"AVERAGE({NL}[band_low])", "#,0"),
        "Band 80% high": (f"AVERAGE({NL}[band_high])", "#,0"),
        "80% band coverage": (f"DIVIDE(COUNTROWS(FILTER({NL}, NOT ISBLANK({NL}[band_low]) && {NL}[actual] >= {NL}[band_low] && "
                              f"{NL}[actual] <= {NL}[band_high])), COUNTROWS(FILTER({NL}, NOT ISBLANK({NL}[band_low]))))", "0.0%"),
        "Model bias excl. outages (MW)": ("CALCULATE([Model bias (MW)], " + NL + "[telemetry_outage] = FALSE())", "#,0"),
        "Days evaluated": (f"DISTINCTCOUNT({NL}[date])", "#,0"),
        "Days model wins": ("SUMX(VALUES(dim_date[date]), IF(NOT ISBLANK([Model MAE (MW)]) && [Model MAE (MW)] < [Benchmark MAE (MW)], 1, 0))", "#,0"),
        "Days model wins (%)": ("DIVIDE([Days model wins], [Days evaluated])", "0%"),
        "Headline scoreboard": ('IF(ISBLANK([Model MAE (MW)]), "No data for this selection", "Model error is " & FORMAT(ABS([Error reduction vs benchmark]), "0.0%") & '
                                'IF([Error reduction vs benchmark] >= 0, " lower", " higher") & " than the benchmark, beating it on " & '
                                'FORMAT([Days model wins (%)], "0%") & " of days")', ""),
    },
    "fact_components": {
        "Headline components": ('VAR mx = MAXX(VALUES(fact_components[component]), [Component model MAE (MW)]) '
                                'VAR comp = CONCATENATEX(FILTER(VALUES(fact_components[component]), [Component model MAE (MW)] = mx), fact_components[component], ", ") '
                                'VAR r = [Component error reduction] '
                                'RETURN IF(ISBLANK(mx), "No data for this selection", "Largest error source: " & comp & " (" & FORMAT(mx, "#,0") & '
                                '" MW MAE). Across components the model " & IF(r >= 0, "cuts error by ", "adds error of ") & FORMAT(ABS(r), "0.0%") & " vs the benchmark")', ""),
        "Component model MAE (MW)": ("AVERAGEX(fact_components, " + ERRO.format(t="fact_components") + ")", "#,0"),
        "Component benchmark MAE (MW)": ("AVERAGEX(fact_components, ABS(fact_components[benchmark] - fact_components[actual]))", "#,0"),
        "Component error reduction": ("DIVIDE([Component benchmark MAE (MW)] - [Component model MAE (MW)], [Component benchmark MAE (MW)])", "0.0%"),
        "Component bias (MW)": ("AVERAGEX(fact_components, fact_components[forecast] - fact_components[actual])", "#,0"),
    },
    "fact_forecast": {
        "Latest decision": ("CALCULATE(MAX(fact_forecast[decision_date]), ALL(fact_forecast))", "yyyy-mm-dd"),
        "Average forecast (MW)": ("VAR d = [Latest decision] RETURN CALCULATE(AVERAGE(fact_forecast[forecast]), fact_forecast[decision_date] = d)", "#,0"),
        "Forecast band low": ("VAR d = [Latest decision] RETURN CALCULATE(AVERAGE(fact_forecast[band_low]), fact_forecast[decision_date] = d)", "#,0"),
        "Forecast band high": ("VAR d = [Latest decision] RETURN CALCULATE(AVERAGE(fact_forecast[band_high]), fact_forecast[decision_date] = d)", "#,0"),
        "Forecast benchmark (MW)": ("VAR d = [Latest decision] RETURN CALCULATE(AVERAGE(fact_forecast[benchmark]), fact_forecast[decision_date] = d)", "#,0"),
        "Forecast peak (MW)": ("VAR d = [Latest decision] RETURN CALCULATE(MAX(fact_forecast[forecast]), fact_forecast[decision_date] = d)", "#,0"),
        "Headline forecast": ('VAR d = [Latest decision] RETURN IF(ISBLANK([Average forecast (MW)]), "No forecast for this selection", '
                              '"Net load expected to average " & FORMAT([Average forecast (MW)] / 1000, "0.0") & " GW, peaking at " & '
                              'FORMAT([Forecast peak (MW)] / 1000, "0.0") & " GW (decision of " & FORMAT(d, "mmm d") & ")")', ""),
    },
    "fact_audit": {
        "Audit model MAE (MW)": ("AVERAGEX(fact_audit, " + ERRO.format(t="fact_audit") + ")", "#,0"),
        "Audit benchmark MAE (MW)": ("AVERAGEX(fact_audit, ABS(fact_audit[benchmark] - fact_audit[actual]))", "#,0"),
        "Audit error reduction": ("DIVIDE([Audit benchmark MAE (MW)] - [Audit model MAE (MW)], [Audit benchmark MAE (MW)])", "0.0%"),
        "Audit actual (MW)": ("AVERAGE(fact_audit[actual])", "#,0"),
        "Audit forecast (MW)": ("AVERAGE(fact_audit[forecast])", "#,0"),
        "Headline audit": ('IF(ISBLANK([Audit model MAE (MW)]), "No audit for this selection", "Replay of " & FORMAT(MIN(fact_audit[date]), "mmm d") & '
                           '"–" & FORMAT(MAX(fact_audit[date]), "mmm d") & ": model error " & FORMAT(ABS([Audit error reduction]), "0.0%") & '
                           'IF([Audit error reduction] >= 0, " below", " above") & " the benchmark")', ""),
    },
    "fact_system_daily": {
        "Total generation (MW)": ("[Hydro (MW)] + [Thermal (MW)] + [Wind (MW)] + [Solar (MW)]", "#,0"),
        "Hydro share": ("DIVIDE([Hydro (MW)], [Total generation (MW)])", "0.0%"),
        "Thermal share": ("DIVIDE([Thermal (MW)], [Total generation (MW)])", "0.0%"),
        "Wind + solar share": ("DIVIDE([Wind (MW)] + [Solar (MW)], [Total generation (MW)])", "0.0%"),
        "Headline system": ('IF(ISBLANK([Hydro (MW)]), "No data for this selection", "Hydro supplied " & FORMAT([Hydro share], "0%") & '
                            '" of generation in this period, wind and solar " & FORMAT([Wind + solar share], "0%") & ", thermal " & FORMAT([Thermal share], "0%"))', ""),
        "Load (MW)": ("AVERAGE(fact_system_daily[load_mw])", "#,0"),
        "Wind (MW)": ("AVERAGE(fact_system_daily[wind_mw])", "#,0"),
        "Solar (MW)": ("AVERAGE(fact_system_daily[solar_mw])", "#,0"),
        "Hydro (MW)": ("AVERAGE(fact_system_daily[hydro_mw])", "#,0"),
        "Thermal (MW)": ("AVERAGE(fact_system_daily[thermal_mw])", "#,0"),
        "Net load (MW)": ("AVERAGE(fact_system_daily[net_load_mw])", "#,0"),
        "Inflow % of long-term mean": ("AVERAGE(fact_system_daily[inflow_pct_ltm]) / 100", "0%"),
        "Wind curtailment (MW)": ("AVERAGE(fact_system_daily[wind_curtailment_mw])", "#,0"),
        "Solar curtailment (MW)": ("AVERAGE(fact_system_daily[solar_curtailment_mw])", "#,0"),
        "Marginal cost SE (R$/MWh)": ("AVERAGE(fact_system_daily[cmo_se])", "#,0.00"),
    },
    "fact_price_daily": {"Spot price est. (R$/MWh)": ("AVERAGE(fact_price_daily[price_est])", "#,0.00")},
    "fact_storage_daily": {"Reservoir storage %": ("AVERAGE(fact_storage_daily[storage_pct]) / 100", "0.0%")},
    "fact_inflow_basin": {"Basin inflow % of mean": ("AVERAGE(fact_inflow_basin[inflow_pct_ltm]) / 100", "0%"),
                          "Basin inflow (MW)": ("SUM(fact_inflow_basin[inflow_mw])", "#,0")},
}
SIN_PADRAO = 'VAR _s = SELECTEDVALUE(dim_subsystem[subsystem], "SIN") RETURN CALCULATE({}, dim_subsystem[subsystem] = _s)'
BASE_SIN = {NL: ["Model MAE (MW)", "Benchmark MAE (MW)", "ONS schedule MAE (MW)", "Model bias (MW)", "MAPE model", "Actual (MW)", "Forecast (MW)",
                 "Benchmark (MW)", "Band 80% low", "Band 80% high", "80% band coverage", "Days evaluated"],
            "fact_audit": ["Audit model MAE (MW)", "Audit benchmark MAE (MW)", "Audit actual (MW)", "Audit forecast (MW)"]}
# With no subsystem selected, hourly tables would sum SIN + regions: base measures default to SIN.
for _t, _nomes in BASE_SIN.items():
    for _n in _nomes:
        _dax, _fmt = MEDIDAS[_t][_n]
        MEDIDAS[_t][_n] = (SIN_PADRAO.format(_dax), _fmt)
for _n, (_dax, _fmt) in list(MEDIDAS["fact_forecast"].items()):
    if _dax.startswith("VAR d = [Latest decision] RETURN CALCULATE("):
        _dax = _dax.replace("RETURN CALCULATE(", 'VAR _s = SELECTEDVALUE(dim_subsystem[subsystem], "SIN") RETURN CALCULATE(', 1)
        MEDIDAS["fact_forecast"][_n] = (_dax[:-1] + ", dim_subsystem[subsystem] = _s)", _fmt)
CHAVES = {"date": "dim_date", "hour": "dim_hour", "subsystem": "dim_subsystem"}
ORDEM = {"dim_subsystem": {"name": "sort_order"}, "dim_date": {"month_name": "month", "weekday": "weekday_num"}}


def nome(x):
    return x if x.isidentifier() and x.isascii() else "'" + x.replace("'", "''") + "'"


def tabela_tmdl(tabela, esquema):
    linhas = [f"table {tabela}"]
    if tabela == "dim_date":
        linhas.append(f"{T}dataCategory: Time")
    linhas.append("")
    for medida, (dax, formato) in MEDIDAS.get(tabela, {}).items():
        linhas += [f"{T}measure {nome(medida)} = {dax}"] + ([f"{T}{T}formatString: {formato}"] if formato else []) + [""]
    tipos_m = []
    for campo in esquema:
        if campo.name in DATAS:
            tipo, tipo_m = "dateTime", "type date"
        elif str(campo.type).startswith("timestamp"):
            tipo, tipo_m = "dateTime", "type datetime"
        else:
            tipo = TIPOS.get(str(campo.type), "string")
            tipo_m = {"int64": "Int64.Type", "double": "type number", "boolean": "type logical", "string": "type text"}[tipo]
        tipos_m.append(f'{{"{campo.name}", {tipo_m}}}')
        linhas.append(f"{T}column {nome(campo.name)}")
        linhas.append(f"{T}{T}dataType: {tipo}")
        if tipo == "dateTime":
            linhas.append(f"{T}{T}formatString: " + ("yyyy-mm-dd" if campo.name in DATAS else "yyyy-mm-dd hh:nn"))
        if tabela == "dim_date" and campo.name == "date":
            linhas.append(f"{T}{T}isKey")
        resumo = "sum" if tipo in ("int64", "double") and campo.name not in CHAVES and not tabela.startswith("dim_") else "none"
        linhas.append(f"{T}{T}summarizeBy: {resumo}")
        linhas.append(f"{T}{T}sourceColumn: {campo.name}")
        if campo.name in ORDEM.get(tabela, {}):
            linhas.append(f"{T}{T}sortByColumn: {ORDEM[tabela][campo.name]}")
        linhas.append("")
    m = [f"let",
         f'    Fonte = Parquet.Document(File.Contents(PastaDados & "{tabela}.parquet")),',
         f"    Tipos = Table.TransformColumnTypes(Fonte, {{{', '.join(tipos_m)}}})",
         f"in",
         f"    Tipos"]
    linhas += [f"{T}partition {tabela} = m", f"{T}{T}mode: import", f"{T}{T}source ="]
    linhas += [f"{T}{T}{T}{T}{x}" for x in m]
    return "\n".join(linhas) + "\n"


TEMAS = Path(r"C:\Program Files\Microsoft Power BI Desktop\bin\WebView2Resources\minerva\sharedresources\BaseThemes")


def copiar_tema():
    """Latest base theme of the installed Power BI, copied into the project (as Desktop does when saving)."""
    destino = RELATORIO / "StaticResources" / "SharedResources" / "BaseThemes"
    existentes = sorted(destino.glob("CY*.json"))
    instalados = sorted(TEMAS.glob("CY*.json")) if TEMAS.exists() else []
    if instalados:
        destino.mkdir(parents=True, exist_ok=True)
        alvo = destino / instalados[-1].name
        alvo.write_bytes(instalados[-1].read_bytes())
        return alvo
    if existentes:
        return existentes[-1]
    raise SystemExit("Power BI base theme not found: install Power BI Desktop or copy a BaseThemes/CY*.json to " + str(destino))


def escrever(caminho, texto):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8", newline="\n")


def main():
    origem = DATA_DIR / "bi"
    arquivos = sorted(origem.glob("*.parquet"))
    if not arquivos:
        print("Run first: scripts/exportar_bi.py")
        return 1
    definicao = MODELO / "definition"
    for velho in (definicao / "tables").glob("*.tmdl"):
        velho.unlink()
    relacoes = []
    for arquivo in arquivos:
        tabela = arquivo.stem
        esquema = pq.read_schema(arquivo)
        escrever(definicao / "tables" / f"{tabela}.tmdl", tabela_tmdl(tabela, esquema))
        if tabela.startswith("fact_"):
            for coluna, dim in CHAVES.items():
                if coluna in esquema.names:
                    relacoes += [f"relationship {tabela}_{coluna}", f"{T}fromColumn: {tabela}.{coluna}", f"{T}toColumn: {dim}.{coluna}", ""]
    escrever(definicao / "relationships.tmdl", "\n".join(relacoes))
    escrever(definicao / "database.tmdl", f"database\n{T}compatibilityLevel: 1600\n")
    escrever(definicao / "model.tmdl", f"model Model\n{T}culture: en-US\n{T}defaultPowerBIDataSourceVersion: powerBI_V3\n"
                                        f"{T}discourageImplicitMeasures\n{T}sourceQueryCulture: en-US\n")
    pasta = str(origem.resolve()) + "\\"
    escrever(definicao / "expressions.tmdl",
             f'expression PastaDados = "{pasta}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
             f"{T}annotation PBI_ResultType = Text\n")
    escrever(MODELO / "definition.pbism", json.dumps({"version": "4.0", "settings": {}}, indent=2) + "\n")
    escrever(RELATORIO / "definition.pbir", json.dumps({"version": "4.0", "datasetReference": {"byPath": {"path": "../Energia.SemanticModel"}}}, indent=2) + "\n")
    # Pages (PBIR format): (re)generated only with --relatorio or if missing, so Desktop edits are not lost.
    if "--relatorio" in sys.argv or not (RELATORIO / "definition" / "pages").exists():
        print(f"PBIR report: {escrever_pbir(RELATORIO, MEDIDAS, copiar_tema().stem)} visuals")
    escrever(BI / "Energia.pbip", json.dumps({"version": "1.0", "artifacts": [{"report": {"path": "Energia.Report"}}],
                                              "settings": {"enableAutoRecovery": True}}, indent=2) + "\n")
    escrever(BI / ".gitignore", "**/.pbi/\n")   # Desktop local settings and cache
    print(f"Project generated in {BI} ({len(arquivos)} tables, {len(relacoes) // 4} relationships, "
          f"{sum(len(v) for v in MEDIDAS.values())} measures). Open bi/Energia.pbip in Power BI Desktop and click Refresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
