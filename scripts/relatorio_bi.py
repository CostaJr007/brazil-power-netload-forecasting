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
    "dataColors": [ROXO, CINZA, LILAS, ROXO_ESCURO, PRETO, CINZA_CLARO, "#5A0090", "#E9D2FF"],
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


def _lit(valor):
    if isinstance(valor, bool):
        return {"Literal": {"Value": "true" if valor else "false"}}
    if isinstance(valor, int):
        return {"Literal": {"Value": f"{valor}L"}}
    if isinstance(valor, float):
        return {"Literal": {"Value": f"{valor}D"}}
    return {"Literal": {"Value": "'" + str(valor).replace("'", "''") + "'"}}


def _cor(hexa):
    return {"solid": {"color": _lit(hexa)}}


class Consulta:
    """Monta o prototypeQuery: um apelido por tabela, Select de colunas e medidas, OrderBy opcional."""

    def __init__(self, medidas):
        self.medidas, self.de, self.sel = medidas, {}, []

    def _alias(self, tabela):
        if tabela not in self.de:
            self.de[tabela] = f"t{len(self.de)}"
        return self.de[tabela]

    def campo(self, ref):
        tabela, nome = ref.split(".", 1)
        expr = {"Expression": {"SourceRef": {"Source": self._alias(tabela)}}, "Property": nome}
        return {("Measure" if nome in self.medidas.get(tabela, {}) else "Column"): expr}

    def selecionar(self, ref):
        if ref not in [s["Name"] for s in self.sel]:
            self.sel.append({**self.campo(ref), "Name": ref})
        return {"queryRef": ref}

    def json(self, ordem=None):
        q = {"Version": 2, "From": [{"Name": a, "Entity": t, "Type": 0} for t, a in self.de.items()], "Select": self.sel}
        if ordem:
            q["OrderBy"] = [{"Direction": 1, "Expression": self.campo(ordem)}]
        return q


def filtro_in(ref, valores):
    """Filtro categórico 'campo em (valores)', usado em segmentações com seleção padrão."""
    tabela, nome = ref.split(".", 1)
    coluna = {"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": nome}}
    return {"Version": 2, "From": [{"Name": "f", "Entity": tabela, "Type": 0}],
            "Where": [{"Condition": {"In": {"Expressions": [coluna], "Values": [[_lit(v)] for v in valores]}}}]}


def _container(n, x, y, w, h, sv):
    config = {"name": f"v{n:03d}", "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": n, "width": w, "height": h}}], "singleVisual": sv}
    return {"x": x, "y": y, "z": n, "width": w, "height": h, "config": json.dumps(config, ensure_ascii=False), "filters": "[]"}


def visual(medidas, n, tipo, x, y, w, h, papeis, titulo=None, ordem=None, selecionado=None, objetos=None, cores=None):
    """cores: {"tabela.medida": "#hex"} fixa a cor de cada série (a legenda do título passa a valer sempre)."""
    q = Consulta(medidas)
    projecoes = {papel: [q.selecionar(r) for r in refs] for papel, refs in papeis.items()}
    for papel in ("Category", "Rows"):
        if papel in projecoes:
            projecoes[papel][0]["active"] = True
    sv = {"visualType": tipo, "projections": projecoes, "prototypeQuery": q.json(ordem), "drillFilterOtherVisuals": True}
    obj = dict(objetos or {})
    if cores:
        obj["dataPoint"] = [{"properties": {"fill": _cor(c)}, "selector": {"metadata": ref}} for ref, c in cores.items()]
    if tipo == "slicer":
        obj["data"] = [{"properties": {"mode": _lit("Dropdown")}}]
        if selecionado:
            ref, valores = selecionado
            obj["general"] = [{"properties": {"filter": {"filter": filtro_in(ref, valores)}}}]
            obj["selection"] = [{"properties": {"singleSelect": _lit(True)}}]
    if obj:
        sv["objects"] = obj
    sv["vcObjects"] = {"title": [{"properties": {"show": _lit(bool(titulo)), **({"text": _lit(titulo)} if titulo else {})}}]}
    return _container(n, x, y, w, h, sv)


def texto(n, x, y, w, h, partes):
    """Caixa de texto; partes = [(texto, tamanho, cor, negrito)]."""
    paragrafos = [{"textRuns": [{"value": t, "textStyle": {"fontSize": f"{tam}pt", "color": cor, **({"fontWeight": "bold"} if negrito else {})}}]}
                  for t, tam, cor, negrito in partes]
    sv = {"visualType": "textbox", "drillFilterOtherVisuals": True, "objects": {"general": [{"properties": {"paragraphs": paragrafos}}]},
          "vcObjects": {"background": [{"properties": {"show": _lit(False)}}]}}
    return _container(n, x, y, w, h, sv)


def paginas(medidas):
    """5 páginas em grade de 1280 × 720: rótulo + manchete, KPIs, gráficos e rodapé com fonte e definições."""
    v = lambda *a, **k: visual(medidas, *a, **k)  # noqa: E731

    def cabecalho(n, rotulo, manchete_medida):
        manchete = v(n + 1, "card", 20, 34, 860, 52, {"Values": [manchete_medida]},
                     objetos={"labels": [{"properties": {"fontSize": _lit(15.0), "color": _cor(PRETO)}}],
                              "categoryLabels": [{"properties": {"show": _lit(False)}}],
                              "background": [{"properties": {"show": _lit(False)}}]})
        return [texto(n, 20, 6, 860, 30, [(rotulo.upper(), 9, ROXO, True)]), manchete]

    def rodape(n, pagina):
        return texto(n, 20, 688, 1240, 30, [(RODAPES[pagina], 7, CINZA, False)])

    def segmentacao(n, x, ref, titulo, padrao=None, w=150):
        return v(n, "slicer", x, 20, w, 56, {"Values": [ref]}, titulo, selecionado=(ref, padrao) if padrao else None)

    def kpi(n, x, y, ref, w):
        return v(n, "card", x, y, w, 96, {"Values": [ref]},
                 objetos={"labels": [{"properties": {"fontSize": _lit(24.0), "color": _cor(PRETO)}}],
                          "categoryLabels": [{"properties": {"color": _cor(CINZA)}}]})

    sin = ["SIN"]
    fc, nl, cp, au, sy = "fact_forecast.", "fact_net_load.", "fact_components.", "fact_audit.", "fact_system_daily."
    modelo_regua = {nl + "Model MAE (MW)": ROXO, nl + "Benchmark MAE (MW)": CINZA_CLARO}

    previsao = [
        *cabecalho(1, "Day-ahead net load forecast · Brazil power system", fc + "Headline forecast"),
        segmentacao(3, 900, "dim_subsystem.subsystem", "Subsystem", sin, 120),
        segmentacao(4, 1030, fc + "date", "Target day", w=120),
        segmentacao(5, 1160, fc + "step", "Step", w=100),
        kpi(6, 20, 100, fc + "Latest decision", 300),
        kpi(7, 330, 100, fc + "Average forecast (MW)", 300),
        kpi(8, 640, 100, fc + "Forecast peak (MW)", 300),
        kpi(9, 950, 100, fc + "Forecast benchmark (MW)", 310),
        v(10, "lineChart", 20, 210, 1240, 470,
          {"Category": ["dim_hour.hour_label"], "Y": [fc + "Average forecast (MW)", fc + "Forecast benchmark (MW)",
                                                      fc + "Forecast band low", fc + "Forecast band high"]},
          "Net load (load − wind − solar), MW by hour: forecast (purple), 80% band (lilac), benchmark (grey)", ordem="dim_hour.hour_label",
          cores={fc + "Average forecast (MW)": ROXO, fc + "Forecast benchmark (MW)": CINZA, fc + "Forecast band low": LILAS, fc + "Forecast band high": LILAS}),
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
        v(31, "clusteredColumnChart", 20, 206, 620, 236, {"Category": ["dim_date.year_month"], "Y": list(modelo_regua)},
          "MAE by month (MW): model (purple) vs benchmark (grey)", ordem="dim_date.year_month", cores=modelo_regua),
        v(32, "lineChart", 660, 206, 600, 236, {"Category": ["dim_hour.hour"], "Y": list(modelo_regua)},
          "MAE by hour of day (MW): late morning, when solar ramps, is the hardest", ordem="dim_hour.hour", cores=modelo_regua),
        v(33, "pivotTable", 20, 452, 620, 230, {"Rows": ["dim_date.day_type"], "Values": [nl + "Model MAE (MW)", nl + "Benchmark MAE (MW)",
                                                                                        nl + "Model bias (MW)", nl + "Days evaluated"]},
          "By day type: holidays and weekends are harder, but the model still beats the benchmark"),
        v(34, "lineChart", 660, 452, 600, 230, {"Category": ["dim_date.date"], "Y": [nl + "Model bias (MW)"]},
          "Daily model bias (MW; below zero = under-forecast)", ordem="dim_date.date", cores={nl + "Model bias (MW)": ROXO}),
        rodape(35, "Model vs ONS"),
    ]
    componentes = [
        *cabecalho(41, "Where the error comes from · load, wind and solar", cp + "Headline components"),
        segmentacao(43, 1020, cp + "horizon", "Horizon", ["D+1"], 90),
        segmentacao(44, 1120, cp + "period", "Period", ["validation (2026)"], 140),
        v(45, "pivotTable", 20, 100, 1240, 260, {"Rows": [cp + "component"], "Columns": ["dim_subsystem.name"],
                                                 "Values": [cp + "Component model MAE (MW)", cp + "Component benchmark MAE (MW)", cp + "Component error reduction"]},
          "MAE by component and subsystem (MW) and error reduction vs the benchmark"),
        v(46, "lineChart", 20, 372, 1240, 310, {"Category": ["dim_date.year_month"], "Y": [cp + "Component bias (MW)"], "Series": [cp + "component"]},
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
        v(58, "lineChart", 20, 210, 1240, 470, {"Category": [au + "timestamp"], "Y": [au + "Audit forecast (MW)", au + "Audit actual (MW)"]},
          "Net load by hour (MW): forecast (purple) vs actual (black)", ordem=au + "timestamp",
          cores={au + "Audit forecast (MW)": ROXO, au + "Audit actual (MW)": PRETO}),
        rodape(59, "Live audit"),
    ]
    sistema = [
        *cabecalho(61, "System context · generation, hydrology and price", sy + "Headline system"),
        segmentacao(63, 1060, "dim_date.year", "Year", [2026], 200),
        v(64, "stackedAreaChart", 20, 100, 620, 290, {"Category": ["dim_date.date"], "Y": [sy + "Hydro (MW)", sy + "Thermal (MW)", sy + "Wind (MW)", sy + "Solar (MW)"]},
          "Daily generation by source, national grid (average MW)", ordem="dim_date.date",
          cores={sy + "Hydro (MW)": ROXO, sy + "Thermal (MW)": CINZA, sy + "Wind (MW)": LILAS, sy + "Solar (MW)": ROXO_ESCURO}),
        v(65, "lineChart", 660, 100, 600, 290, {"Category": ["dim_date.date"], "Y": ["fact_storage_daily.Reservoir storage %"], "Series": ["dim_subsystem.name"]},
          "Reservoir storage by subsystem (% of capacity)", ordem="dim_date.date"),
        v(66, "lineChart", 20, 400, 620, 282, {"Category": ["dim_date.date"], "Y": ["fact_price_daily.Spot price est. (R$/MWh)"], "Series": ["dim_subsystem.name"]},
          "Estimated spot price by subsystem (R$/MWh)", ordem="dim_date.date"),
        v(67, "lineChart", 660, 400, 600, 282, {"Category": ["dim_date.date"], "Y": [sy + "Inflow % of long-term mean"]},
          "Natural inflow, national grid (% of long-term mean)", ordem="dim_date.date", cores={sy + "Inflow % of long-term mean": ROXO}),
        rodape(68, "System & price"),
    ]
    nomes = [("Forecast", previsao), ("Model vs ONS", placar), ("Error drivers", componentes), ("Live audit", auditoria), ("System & price", sistema)]
    return [{"config": "{}", "displayName": nome, "displayOption": 1, "filters": "[]", "height": ALTURA, "name": f"Page{i}",
             "ordinal": i, "visualContainers": vis, "width": LARGURA} for i, (nome, vis) in enumerate(nomes)]


def report_json(medidas, tema_base):
    """Tema base (obrigatório: sem ele o Desktop falha com "reading 'customTheme'") + tema próprio da paleta."""
    config = {"version": "5.70", "activeSectionIndex": 0,
              "themeCollection": {"baseTheme": {"name": tema_base, "version": "5.70", "type": 2},
                                  "customTheme": {"name": TEMA_PROPRIO, "version": "5.70", "type": 1}}}
    pacotes = [{"resourcePackage": {"name": "SharedResources", "type": 2, "disabled": False,
                                    "items": [{"type": 202, "path": f"BaseThemes/{tema_base}.json", "name": tema_base}]}},
               {"resourcePackage": {"name": "RegisteredResources", "type": 1, "disabled": False,
                                    "items": [{"type": 201, "path": TEMA_PROPRIO, "name": TEMA_PROPRIO}]}}]
    return {"config": json.dumps(config), "layoutOptimization": 0, "resourcePackages": pacotes, "sections": paginas(medidas)}
