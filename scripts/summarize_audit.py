# GUIA DE LEITURA — Consolida a auditoria local e corrige a interpretação das datas por tipo de produto.
# Entrada: endpoints_audit.json, load_api_probe.json e arquivos locais da auditoria.
# Saída: atualiza o JSON e o Markdown da auditoria. Não faz novas requisições HTTP.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

"""Finalize observed endpoint evidence without inferring cadastral freshness."""
# Importa json: converte entre texto JSON e estruturas Python.
import json
# De pathlib, importa Path: constrói caminhos de arquivos de forma portátil.
from pathlib import Path
# Importa duckdb: consulta CSV/Parquet usando SQL em processo local.
import duckdb

# De acquire, importa ROOT, atomic_json: reutiliza funções do coletor central em vez de duplicar suas regras.
from acquire import ROOT, atomic_json


# FUNÇÃO main — coordena a sequência descrita no cabeçalho deste arquivo.
# Recebe parâmetros pelo terminal ou pelos arquivos indicados; os detalhes são explicados nos blocos abaixo.
def main():
    # Define path: o caminho local do arquivo usado nesta etapa.
    path = ROOT / "docs/inventory/endpoints_audit.json"
    # Define audit: a auditoria anterior carregada do disco para consolidação.
    audit = json.loads(path.read_text(encoding="utf-8"))
    # Define probes: os resultados dos testes pontuais das duas APIs de carga.
    probes = json.loads((ROOT / "docs/inventory/load_api_probe.json").read_text(encoding="utf-8"))
    # Define cadastral: os datasets cadastrais, cujas datas de eventos não comprovam atualização operacional.
    cadastral = {"reservatorio", "capacidade-geracao", "usina_conjunto", "usina_pqu", "res_cotaareavolume", "bacia_contorno"}
    # Define con: uma conexão DuckDB local para consultas SQL, sem servidor externo.
    con = duckdb.connect()
    # Laço: para cada elemento de audit['results'], associa o valor a item e executa o bloco indentado.
    for item in audit["results"]:
        # Define content: os resultados de leitura do arquivo associado a este conjunto.
        content = item.get("content", {})
        # Condição: item['dataset'] in cadastral.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if item["dataset"] in cadastral:
            # Registra/atualiza o campo 'reference_column' em content; usa o valor literal None.
            content["reference_column"] = None
            # Registra/atualiza o campo 'max_reference' em content; usa o valor literal None.
            content["max_reference"] = None
            # Registra/atualiza o campo 'freshness_assessment' em item; usa o valor literal 'cadastro: HTTP confirmado; atualidade do conteúdo não comprovada por datas de eventos'.
            item["freshness_assessment"] = "cadastro: HTTP confirmado; atualidade do conteúdo não comprovada por datas de eventos"
        # Condição: item['dataset'] in {'carga-energia-verificada', 'carga-energia-programada'}.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if item["dataset"] in {"carga-energia-verificada", "carga-energia-programada"}:
            # Define kind: o tipo de carga: programada ou verificada.
            kind = item["dataset"].split("-")[-1]
            # Registra/atualiza o campo 'api_probe' em item; obtém o primeiro elemento elegível; o padrão evita falhar quando ausente.
            item["api_probe"] = next(p for p in probes if p["kind"] == kind)
            # Registra/atualiza o campo 'status' em item; usa o valor literal 'http_200_empty_response_without_area'.
            item["status"] = "http_200_empty_response_without_area"
        # Condição: item['dataset'] in {'programacao_x_previsao', 'grandezas_fluviometricas'}.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if item["dataset"] in {"programacao_x_previsao", "grandezas_fluviometricas"}:
            # Executa a operação con.read_parquet(content['path']).create_view('sample', replace=True); seu efeito é descrito pela função ou pelo bloco em que aparece.
            con.read_parquet(content["path"]).create_view("sample", replace=True)
            # Define names: os nomes encontrados; o significado exato vem da expressão à direita.
            names = [r[0] for r in con.execute("DESCRIBE sample").fetchall() if r[0].startswith(("dat_", "din_"))]
            # Laço: para cada elemento de names, associa o valor a name e executa o bloco indentado.
            for name in names:
                # Define escaped: o nome de coluna protegido por aspas SQL para evitar erro com caracteres especiais.
                escaped = '"' + name.replace('"', '""') + '"'
                # Define parsed: a expressão SQL que tenta interpretar datas sem abortar em valores inválidos.
                parsed = f"coalesce(try_cast({escaped} AS TIMESTAMP),try_strptime(cast({escaped} AS VARCHAR), '%Y%m%d'))"
                # Define (low, high, count): recebe uma única linha de resultado SQL.
                low, high, count = con.execute(f"SELECT min({parsed}),max({parsed}),count({parsed}) FROM sample").fetchone()
                # Condição: count.
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                if count:
                    # Registra/atualiza o campo name em content['date_columns']; organiza os campos em um dicionário (pares chave: valor).
                    content["date_columns"][name] = {"min": str(low), "max": str(high), "nonnull": count}
                    # Registra/atualiza o campo 'reference_column' em content; calcula a expressão à direita antes de atribuir seu resultado.
                    content["reference_column"] = name
                    # Registra/atualiza o campo 'max_reference' em content; converte o valor para texto.
                    content["max_reference"] = str(high)
        # Condição: item['dataset'] == 'cvu-usitermica'.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if item["dataset"] == "cvu-usitermica":
            # Registra/atualiza o campo 'reference_column' em content; usa o valor literal 'dat_fimsemana'.
            content["reference_column"] = "dat_fimsemana"
            # Registra/atualiza o campo 'max_reference' em content; calcula a expressão à direita antes de atribuir seu resultado.
            content["max_reference"] = content["date_columns"]["dat_fimsemana"]["max"]
    # Define heads: a lista achatada de respostas HEAD dos recursos recentes.
    heads = [e for item in audit["results"] for e in item.get("endpoints", [])]
    # Registra/atualiza o campo 'summary' em audit; organiza os campos em um dicionário (pares chave: valor).
    audit["summary"] = {"datasets": len(audit["results"]), "file_urls_tested": len(heads),
                        # Continua o dicionário: define os campos http_200; cada valor vem da expressão após os dois-pontos.
                        "http_200": sum(e.get("http_status") == 200 for e in heads),
                        # Continua o dicionário: define os campos file_errors; cada valor vem da expressão após os dois-pontos.
                        "file_errors": [e for e in heads if e.get("http_status") != 200],
                        # Continua o dicionário: define os campos load_api; cada valor vem da expressão após os dois-pontos.
                        "load_api": "Both HTTP 200 but empty without area: acquisition not confirmed"}
    # Publica o JSON pelo helper atomic_json: escreve temporário antes de substituir o arquivo final.
    atomic_json(path, audit)
    # Define lines: as linhas de texto que formarão o relatório Markdown.
    lines = ["# Endpoints e atualização observada", "", f"Consulta UTC: {audit['completed_at']}.", "",
             f"{len(audit['results'])} conjuntos selecionados; {len(heads)} URLs de arquivos recentes testadas; {audit['summary']['http_200']} retornaram HTTP 200.", "",
             "As duas APIs de carga responderam HTTP 200 com lista vazia no teste sem área. Não estão aprovadas para coleta até validar código oficial e retorno de observações.", "",
             "| Conjunto | Maior referência lida | Resultado |", "|---|---|---|"]
    # Laço: para cada elemento de audit['results'], associa o valor a item e executa o bloco indentado.
    for item in audit["results"]:
        # Define content: os resultados de leitura do arquivo associado a este conjunto.
        content = item.get("content", {})
        # Define label: o nome legível do recurso ou a descrição usada no relatório.
        label = item["status"]
        # Condição: item['dataset'] in cadastral.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if item["dataset"] in cadastral:
            # Define label: o nome legível do recurso ou a descrição usada no relatório.
            label = "link funciona; atualização cadastral não confirmada"
        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
        lines.append(f"| [{item['dataset']}](https://dados.ons.org.br/dataset/{item['dataset']}) | {content.get('max_reference') or 'não confirmada / não aplicável'} | {label} |")
    # Atualiza lines: soma o valor calculado ao conteúdo anterior.
    lines += ["", "Interpretação: referência recente é evidência de conteúdo recente, não certificação do prazo esperado de cada produto. Datas futuras em programação, CVU e volume de espera podem representar vigência/horizonte. Não confundir com observação realizada. Os horários permanecem como entregues pela fonte, sem conversão de fuso.", "", "O JSON associado contém URLs exatas, códigos HTTP, Last-Modified, hashes e campos de data. Nenhuma conclusão vale para todos os arquivos históricos do bucket."]
    # Serializa/grava o texto no caminho indicado em UTF-8; write_text substitui o conteúdo existente desse arquivo.
    (ROOT / "docs/inventory/endpoints_audit.md").write_text("\n".join(lines), encoding="utf-8")
    # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
    print(json.dumps(audit["summary"], ensure_ascii=False))


# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == "__main__":
    # Executa a operação main(); seu efeito é descrito pela função ou pelo bloco em que aparece.
    main()
