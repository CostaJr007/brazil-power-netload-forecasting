"""Páginas do relatório Power BI (formato report.json), geradas por código. Texto do relatório em inglês (portfólio).

Estilo "consultoria": rótulo roxo, manchete com a conclusão (medida DAX dinâmica), cor com função
(roxo = modelo, cinza = régua, lilás = banda), fundo claro, pouca tinta e rodapé com a fonte de cada página.
Paleta: roxo #A100FF como único destaque, neutros preto/branco/cinza #66646E, roxo escuro #7500C0 e lilás
#D2A5FF para séries, fundo #F2F2F2. Sem logotipos nem nomes de terceiros.

Cada título foi conferido contra os dados (2026, SIN): a hora mais difícil é o fim da manhã (rampa solar),
não a ponta; em feriados o modelo erra mais que em dias úteis, mas ainda bate a régua.
"""
import json

LARGURA, ALTURA = 1280, 720
ROXO, ROXO_ESCURO, LILAS, CINZA, CINZA_CLARO, PRETO, FUNDO = "#A100FF", "#7500C0", "#D2A5FF", "#66646E", "#B4B2B9", "#000000", "#F2F2F2"
TEMA_PROPRIO = "ConsultingPurple.json"
TEMA = {
    "name": "Consulting Purple",
    "dataColors": [ROXO, CINZA, LILAS, PRETO, CINZA_CLARO, ROXO_ESCURO, "#5A0090", "#E9D2FF"],   # séries vizinhas bem distintas
    "background": "#FFFFFF", "foreground": PRETO, "tableAccent": ROXO,
    "good": "#1B7F3B", "bad": "#C62828", "neutral": CINZA,
    "textClasses": {"callout": {"fontFace": "Segoe UI Semibold", "fontSize": 26, "color": PRETO},
                    "title": {"fontFace": "Segoe UI Semibold", "fontSize": 11, "color": PRETO},
                    "header": {"fontFace": "Segoe UI Semibold", "fontSize": 11, "color": PRETO},
                    "label": {"fontFace": "Segoe UI", "fontSize": 10, "color": CINZA}},
    "visualStyles": {
        "*": {"*": {"border": [{"show": False}],
                    "background": [{"show": True, "color": {"solid": {"color": "#FFFFFF"}}, "transparency": 0}],
                    "title": [{"show": True, "fontColor": {"solid": {"color": PRETO}}, "fontSize": 11}],
                    "valueAxis": [{"gridlineColor": {"solid": {"color": "#E6E6E6"}}}]}},
        "page": {"*": {"background": [{"color": {"solid": {"color": FUNDO}}, "transparency": 0}]}},
    },
}
BENCH = ("Benchmark: D+1 = ONS day-ahead schedule (DESSEM); D+2 = previous-day ONS schedule bias-corrected by hour and weekday. "
         "Walk-forward backtest: recipes selected on 2025, validated on 2026. MAE = mean absolute error of hourly values.")
RODAPES = {
    "Forecast": ("Source: ONS open data and Open-Meteo weather forecasts at plant and city locations. Benchmark: previous-day ONS schedule "
                 "bias-corrected by hour and weekday. Band: 80% interval from the model's errors over the previous 120 days."),
    "Model vs ONS": "Source: ONS open data. " + BENCH,
    "Error drivers": "Source: ONS open data. Each component is forecast separately; net load = load − wind − solar. " + BENCH,
    "Live audit": ("Each forecast rebuilt with only the data available at 10 pm the day before (archived weather, frozen recipes). "
                   "Actuals: latest ONS balance; the most recent day is still preliminary."),
    "System & price": ("Source: ONS open data. Spot price estimated from the marginal cost (CMO) with the regulator's floor and cap; "
                       "the official CCEE price was not accessible. Inflow = natural energy inflow vs long-term mean."),
}


SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"


def _lit(valor):
    """Valor de propriedade no formato do Power BI: {"expr": {"Literal": ...}} (sem o "expr" o Desktop descarta)."""
    if isinstance(valor, bool):
        v = "true" if valor else "false"
    elif isinstance(valor, int):
        v = f"{valor}L"
    elif isinstance(valor, float):
        v = f"{valor}D"
    else:
        v = "'" + str(valor).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": v}}}


def _cor(hexa):
    return {"solid": {"color": _lit(hexa)}}


def _props(**kw):
    return [{"properties": {k: (v if isinstance(v, dict) else _lit(v)) for k, v in kw.items()}}]


class Consulta:
    """queryState do PBIR: projeções por papel, com Measure/Column distinguidos pelo dicionário de medidas."""

    def __init__(self, medidas):
        self.medidas = medidas

    def campo(self, ref):
        tabela, nome = ref.split(".", 1)
        expr = {"Expression": {"SourceRef": {"Entity": tabela}}, "Property": nome}
        return {("Measure" if nome in self.medidas.get(tabela, {}) else "Column"): expr}


def filtro_in(ref, valores):
    """Filtro categórico 'campo em (valores)', usado em segmentações com seleção padrão."""
    tabela, nome = ref.split(".", 1)
    coluna = {"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": nome}}
    valores_lit = [[{"Literal": _lit(v)["expr"]["Literal"]}] for v in valores]
    return {"Version": 2, "From": [{"Name": "f", "Entity": tabela, "Type": 0}],
            "Where": [{"Condition": {"In": {"Expressions": [coluna], "Values": valores_lit}}}]}


def _container(n, x, y, w, h, visual):
    return {"$schema": f"{SCHEMA}/visualContainer/2.14.0/schema.json", "name": f"v{n:03d}",
            "position": {"x": x, "y": y, "z": n * 100, "height": h, "width": w}, "visual": visual}


GRAFICOS = {"lineChart", "clusteredColumnChart", "clusteredBarChart", "stackedAreaChart"}


def visual(medidas, n, tipo, x, y, w, h, papeis, titulo=None, ordem=None, selecionado=None, objetos=None, cores=None, finas=None):
    """cores: {"tabela.medida": "#hex"} fixa a cor de cada série; finas: séries com traço fino (ex.: a banda)."""
    q = Consulta(medidas)
    estado = {}
    for papel, refs in papeis.items():
        proj = []
        for k, r in enumerate(refs):
            r, rotulo = r if isinstance(r, tuple) else (r, None)
            item = {"field": q.campo(r), "queryRef": r}
            if rotulo:
                item["displayName"] = rotulo
            if k == 0 and papel in ("Category", "Rows", "Values") and tipo in ("slicer", "lineChart", "clusteredColumnChart", "clusteredBarChart", "stackedAreaChart", "pivotTable"):
                if papel != "Values" or tipo == "slicer":
                    item["active"] = True
            proj.append(item)
        estado[papel] = {"projections": proj}
    query = {"queryState": estado}
    if ordem:
        query["sortDefinition"] = {"sort": [{"field": q.campo(ordem), "direction": "Ascending"}]}
    obj = dict(objetos or {})
    if cores:
        obj["dataPoint"] = [{"properties": {"fill": _cor(c)}, "selector": {"metadata": ref}} for ref, c in cores.items()]
    if finas:
        obj["lineStyles"] = [{"properties": {"strokeWidth": _lit(1)}, "selector": {"metadata": ref}} for ref in finas]
    if tipo in GRAFICOS:
        obj.setdefault("categoryAxis", _props(showAxisTitle=False))
        obj.setdefault("valueAxis", _props(showAxisTitle=False))
        obj.setdefault("legend", _props(show=True, position="Top", showTitle=False))
    if tipo == "slicer":
        obj["data"] = _props(mode="Dropdown")
        obj["header"] = _props(show=False)
        if selecionado:
            ref, valores = selecionado
            obj["general"] = [{"properties": {"filter": {"filter": filtro_in(ref, valores)}}}]
            obj["selection"] = _props(singleSelect=True)
    vc = {"title": _props(show=bool(titulo), **({"text": titulo, "fontSize": 10.0 if tipo == "slicer" else 11.0} if titulo else {}))}
    visual = {"visualType": tipo, "query": query, "objects": obj, "visualContainerObjects": vc, "drillFilterOtherVisuals": True}
    return _container(n, x, y, w, h, visual)


def texto(n, x, y, w, h, partes, fundo=None):
    """Caixa de texto; partes = [(texto, tamanho, cor, negrito)]; fundo = cor de fundo opcional."""
    paragrafos = [{"textRuns": [{"value": t, "textStyle": {"fontSize": f"{tam}pt", "color": cor, **({"fontWeight": "bold"} if negrito else {})}}]}
                  for t, tam, cor, negrito in partes]
    visual = {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paragrafos}}]},
              "visualContainerObjects": {"background": _props(show=True, color=_cor(fundo), transparency=0.0) if fundo else _props(show=False),
                                         **({"padding": _props(left=20.0, top=8.0)} if fundo else {})},
              "drillFilterOtherVisuals": True}
    return _container(n, x, y, w, h, visual)


def paginas(medidas):
    """5 páginas em grade de 1280 × 720: rótulo + manchete, KPIs, gráficos e rodapé com fonte e definições."""
    v = lambda *a, **k: visual(medidas, *a, **k)  # noqa: E731

    def cabecalho(n, rotulo, manchete_medida):
        manchete = v(n + 1, "card", 14, 32, 880, 54, {"Values": [manchete_medida]},
                     objetos={"labels": _props(fontSize=15.0, color=_cor("#FFFFFF"), fontFamily="Segoe UI Semibold"),
                              "categoryLabels": _props(show=False)})
        manchete["visual"]["visualContainerObjects"]["background"] = _props(show=False)
        rotulo_faixa = texto(n, 0, 0, LARGURA, 96, [(rotulo.upper(), 9, ROXO, True)], fundo=PRETO)
        rotulo_faixa["position"]["z"] = 0   # faixa preta atrás da manchete e dos filtros
        return [rotulo_faixa, manchete]

    def rodape(n, pagina):
        return texto(n, 20, 688, 1240, 30, [(RODAPES[pagina], 7, CINZA, False)])

    def segmentacao(n, x, ref, titulo, padrao=None, w=150):
        return v(n, "slicer", x, 20, w, 56, {"Values": [ref]}, titulo, selecionado=(ref, padrao) if padrao else None)

    def kpi(n, x, y, ref, w):
        return v(n, "card", x, y, w, 96, {"Values": [ref]},
                 objetos={"labels": _props(fontSize=22.0, color=_cor(PRETO), labelDisplayUnits=1.0, labelPrecision=0),
                          "categoryLabels": _props(show=True, color=_cor(CINZA), fontSize=9.0)})

    sin = ["SIN"]
    fc, nl, cp, au, sy = "fact_forecast.", "fact_net_load.", "fact_components.", "fact_audit.", "fact_system_daily."
    modelo_regua = {nl + "Model MAE (MW)": ROXO, nl + "Benchmark MAE (MW)": CINZA_CLARO}

    previsao = [
        *cabecalho(1, "Day-ahead net load forecast · Brazil power system", fc + "Headline forecast"),
        segmentacao(3, 900, "dim_subsystem.subsystem", "Subsystem", sin, 120),
        segmentacao(4, 1030, fc + "date", "Target day", w=120),
        segmentacao(5, 1160, fc + "step", "Step", w=100),
        kpi(6, 20, 108, fc + "Latest decision", 300),
        kpi(7, 330, 108, fc + "Average forecast (MW)", 300),
        kpi(8, 640, 108, fc + "Forecast peak (MW)", 300),
        kpi(9, 950, 108, fc + "Forecast benchmark (MW)", 310),
        v(10, "lineChart", 20, 210, 1240, 470,
          {"Category": [("dim_hour.hour_label", "Hour")], "Y": [(fc + "Average forecast (MW)", "Forecast"), (fc + "Forecast benchmark (MW)", "Benchmark"),
                                                                (fc + "Forecast band low", "80% band, low"), (fc + "Forecast band high", "80% band, high")]},
          "Net load (load − wind − solar), MW by hour: forecast (purple), 80% band (lilac), benchmark (grey)", ordem="dim_hour.hour_label",
          cores={fc + "Average forecast (MW)": ROXO, fc + "Forecast benchmark (MW)": CINZA, fc + "Forecast band low": LILAS, fc + "Forecast band high": LILAS},
          finas=[fc + "Forecast band low", fc + "Forecast band high", fc + "Forecast benchmark (MW)"]),
        rodape(11, "Forecast"),
    ]
    placar = [
        *cabecalho(21, "Model vs grid operator · walk-forward backtest", nl + "Headline scoreboard"),
        segmentacao(23, 900, "dim_subsystem.subsystem", "Subsystem", sin, 110),
        segmentacao(24, 1020, nl + "horizon", "Horizon", ["D+1"], 90),
        segmentacao(25, 1120, nl + "period", "Period", ["validation (2026)"], 140),
        kpi(26, 20, 100, nl + "Model MAE (MW)", 240),
        kpi(27, 270, 100, nl + "Benchmark MAE (MW)", 240),
        kpi(28, 520, 100, nl + "Error reduction vs benchmark", 240),
        kpi(29, 770, 100, nl + "Days model wins (%)", 240),
        kpi(30, 1020, 100, nl + "80% band coverage", 240),
        v(31, "clusteredColumnChart", 20, 206, 620, 236, {"Category": [("dim_date.year_month", "Month")], "Y": [(nl + "Model MAE (MW)", "Model"), (nl + "Benchmark MAE (MW)", "Benchmark")]},
          "MAE by month (MW): model (purple) vs benchmark (grey)", ordem="dim_date.year_month", cores=modelo_regua),
        v(32, "lineChart", 660, 206, 600, 236, {"Category": [("dim_hour.hour_label", "Hour")], "Y": [(nl + "Model MAE (MW)", "Model"), (nl + "Benchmark MAE (MW)", "Benchmark")]},
          "MAE by hour of day (MW): late morning, when solar ramps, is the hardest", ordem="dim_hour.hour_label", cores=modelo_regua),
        v(33, "pivotTable", 20, 452, 620, 230, {"Rows": [("dim_date.day_type", "Day type")], "Values": [(nl + "Model MAE (MW)", "Model MAE (MW)"),
                                                                                                    (nl + "Benchmark MAE (MW)", "Benchmark MAE (MW)"),
                                                                                                    (nl + "Model bias (MW)", "Bias (MW)"), (nl + "Days evaluated", "Days")]},
          "By day type: holidays and weekends are harder, but the model still beats the benchmark"),
        v(34, "lineChart", 660, 452, 600, 230, {"Category": [("dim_date.date", "Date")], "Y": [(nl + "Model bias excl. outages (MW)", "Bias")]},
          "Daily model bias (MW; below zero = under-forecast), ONS telemetry-outage days excluded", ordem="dim_date.date",
          cores={nl + "Model bias excl. outages (MW)": ROXO}),
        rodape(35, "Model vs ONS"),
    ]
    componentes = [
        *cabecalho(41, "Where the error comes from · load, wind and solar", cp + "Headline components"),
        segmentacao(43, 1020, cp + "horizon", "Horizon", ["D+1"], 90),
        segmentacao(44, 1120, cp + "period", "Period", ["validation (2026)"], 140),
        v(45, "pivotTable", 20, 108, 620, 252, {"Rows": [(cp + "component", "Component")], "Columns": [("dim_subsystem.name", "Subsystem")],
                                                "Values": [(cp + "Component error reduction", "Error reduction")]},
          "Error reduction vs the benchmark, by component and subsystem"),
        v(48, "clusteredBarChart", 660, 108, 600, 252, {"Category": [(cp + "component", "Component")],
                                                         "Y": [(cp + "Component model MAE (MW)", "Model"), (cp + "Component benchmark MAE (MW)", "Benchmark")]},
          "MAE by component, all subsystems (MW): model (purple) vs benchmark (grey)",
          cores={cp + "Component model MAE (MW)": ROXO, cp + "Component benchmark MAE (MW)": CINZA_CLARO}),
        v(46, "lineChart", 20, 372, 1240, 310, {"Category": [("dim_date.year_month", "Month")], "Y": [(cp + "Component bias (MW)", "Bias")], "Series": [(cp + "component", "Component")]},
          "Monthly bias by component (MW; above zero = over-forecast)", ordem="dim_date.year_month"),
        rodape(47, "Error drivers"),
    ]
    auditoria = [
        *cabecalho(51, "Live replay · forecasts as issued at 10 pm the day before", au + "Headline audit"),
        segmentacao(53, 1020, "dim_subsystem.subsystem", "Subsystem", sin, 110),
        segmentacao(54, 1140, au + "step", "Step", ["D+1"], 120),
        kpi(55, 20, 100, au + "Audit model MAE (MW)", 405),
        kpi(56, 437, 100, au + "Audit benchmark MAE (MW)", 405),
        kpi(57, 855, 100, au + "Audit error reduction", 405),
        v(58, "lineChart", 20, 210, 1240, 470, {"Category": [(au + "timestamp", "Hour")], "Y": [(au + "Audit forecast (MW)", "Forecast"), (au + "Audit actual (MW)", "Actual")]},
          "Net load by hour (MW): forecast (purple) vs actual (black)", ordem=au + "timestamp",
          cores={au + "Audit forecast (MW)": ROXO, au + "Audit actual (MW)": PRETO}),
        rodape(59, "Live audit"),
    ]
    sistema = [
        *cabecalho(61, "System context · generation, hydrology and price", sy + "Headline system"),
        segmentacao(63, 1060, "dim_date.year", "Year", [2026], 200),
        v(64, "stackedAreaChart", 20, 100, 620, 290, {"Category": [("dim_date.year_month", "Month")], "Y": [(sy + "Hydro (MW)", "Hydro"), (sy + "Wind (MW)", "Wind"), (sy + "Solar (MW)", "Solar"), (sy + "Thermal (MW)", "Thermal")]},
          "Monthly generation by source, national grid (average MW)", ordem="dim_date.year_month",
          cores={sy + "Hydro (MW)": ROXO, sy + "Wind (MW)": LILAS, sy + "Solar (MW)": CINZA_CLARO, sy + "Thermal (MW)": CINZA}),
        v(65, "lineChart", 660, 100, 600, 290, {"Category": ["dim_date.date"], "Y": ["fact_storage_daily.Reservoir storage %"], "Series": ["dim_subsystem.name"]},
          "Reservoir storage by subsystem (% of capacity)", ordem="dim_date.date"),
        v(66, "lineChart", 20, 400, 620, 282, {"Category": ["dim_date.date"], "Y": ["fact_price_daily.Spot price est. (R$/MWh)"], "Series": ["dim_subsystem.name"]},
          "Estimated spot price by subsystem (R$/MWh)", ordem="dim_date.date"),
        v(67, "lineChart", 660, 400, 600, 282, {"Category": ["dim_date.date"], "Y": [sy + "Inflow % of long-term mean"]},
          "Natural inflow, national grid (% of long-term mean)", ordem="dim_date.date", cores={sy + "Inflow % of long-term mean": ROXO}),
        rodape(68, "System & price"),
    ]
    return [("Forecast", previsao), ("Model vs ONS", placar), ("Error drivers", componentes), ("Live audit", auditoria), ("System & price", sistema)]


def _json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def escrever_pbir(relatorio, medidas, tema_base):
    """Relatório no formato PBIR (o que o Desktop grava): definition/report.json, pages/*/page.json, visuals/*/visual.json."""
    import shutil
    definicao = relatorio / "definition"
    if definicao.exists():
        shutil.rmtree(definicao)
    (relatorio / "report.json").unlink(missing_ok=True)   # formato antigo
    versao = {"visual": "2.6.0", "report": "3.1.0", "page": "2.3.0"}
    _json(definicao / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    _json(definicao / "report.json", {
        "$schema": f"{SCHEMA}/report/3.3.0/schema.json",
        "themeCollection": {"baseTheme": {"name": tema_base, "reportVersionAtImport": versao, "type": "SharedResources"},
                            "customTheme": {"name": TEMA_PROPRIO, "reportVersionAtImport": versao, "type": "RegisteredResources"}},
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                              "items": [{"name": tema_base, "path": f"BaseThemes/{tema_base}.json", "type": "BaseTheme"}]},
                             {"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": TEMA_PROPRIO, "path": TEMA_PROPRIO, "type": "CustomTheme"}]}]})
    _json(relatorio / "StaticResources" / "RegisteredResources" / TEMA_PROPRIO, TEMA)
    ordem, total = [], 0
    for i, (nome, visuais) in enumerate(paginas(medidas)):
        pagina = f"Page{i}"
        ordem.append(pagina)
        _json(definicao / "pages" / pagina / "page.json", {"$schema": f"{SCHEMA}/page/2.1.0/schema.json", "name": pagina,
                                                          "displayName": nome, "displayOption": "FitToPage", "height": ALTURA, "width": LARGURA})
        for vis in visuais:
            _json(definicao / "pages" / pagina / "visuals" / vis["name"] / "visual.json", vis)
            total += 1
    _json(definicao / "pages" / "pages.json", {"$schema": f"{SCHEMA}/pagesMetadata/1.1.0/schema.json", "pageOrder": ordem, "activePageName": ordem[0]})
    return total
