# GUIA DE LEITURA — Audita os recursos recentes dos conjuntos selecionados: testa HTTP e lê datas internas dos arquivos.
# Entrada: configs/ons.json e catálogo remoto. Saída: data/endpoint_audit e relatório em docs/inventory.
# Atenção: executar este arquivo faz novas requisições e substitui o relatório da auditoria mais recente.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

"""Live endpoint and latest-reference audit for the curated ONS selection.

Does not claim historical completeness or physical correctness.
"""
# Importa concurrent.futures: executa algumas tarefas de rede em paralelo com limite de trabalhadores.
import concurrent.futures
# Importa hashlib: calcula assinaturas dos bytes para identificar conteúdos.
import hashlib
# Importa json: converte entre texto JSON e estruturas Python.
import json
# Importa re: procura padrões de texto usando expressões regulares.
import re
# De datetime, importa datetime, timezone: representa datas, horários e UTC.
from datetime import datetime, timezone
# De pathlib, importa Path: constrói caminhos de arquivos de forma portátil.
from pathlib import Path
# De urllib.request, importa Request, urlopen: faz requisições HTTP pela biblioteca padrão.
from urllib.request import Request, urlopen

# Importa duckdb: consulta CSV/Parquet usando SQL em processo local.
import duckdb

# De acquire, importa ROOT, atomic_json, json_get, utcnow: reutiliza funções do coletor central em vez de duplicar suas regras.
# Scripts desta subpasta reutilizam os módulos de scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import DATA_DIR, ROOT, atomic_json, json_get, utcnow


# FUNÇÃO resource_date — Extrai uma data aproximada do nome/URL do recurso para escolher o arquivo mais recente. É uma heurística de seleção; a confirmação vem da leitura dos registros.
def resource_date(resource):
    # Define text: calcula a expressão à direita antes de atribuir seu resultado.
    text = resource.get("url", "") + " " + resource.get("name", "")
    # Define matches: calcula a expressão à direita antes de atribuir seu resultado.
    matches = re.findall(r"(20\d{2})(?:[-_](\d{2}))?(?:[-_](\d{2}))?", text)
    # Devolve o resultado ao chamador: obtém o maior valor segundo a ordem definida.
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return max(((int(y), int(m or 1), int(d or 1)) for y, m, d in matches), default=(0, 0, 0))


# FUNÇÃO request — Recebe URL e método HTTP e abre a resposta com timeout. HEAD solicita cabeçalhos; GET solicita conteúdo. Não contém a política de repetição de open_http.
def request(url, method="GET"):
    # Avalia a expressão de retorno abaixo e devolve esse valor ao chamador, sem criar uma nova atribuição.
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return urlopen(Request(url, method=method, headers={"User-Agent": "EnergyDataStudy/0.1"}), timeout=30)


# FUNÇÃO head — Recebe metadados de um recurso e devolve status HTTP e cabeçalhos, ou erro. Não lê os registros do arquivo; Last-Modified descreve o objeto HTTP.
def head(resource):
    # Define result: o resultado desta operação, que será retornado, impresso ou salvo.
    result = {"resource_id": resource["id"], "format": resource.get("format"), "url": resource["url"]}
    # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
    try:
        # Abre um contexto com request(resource['url'], 'HEAD').
        # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
        with request(resource["url"], "HEAD") as response:
            # Atualiza o acumulador de hash ou os campos do dicionário, conforme o objeto antes do ponto.
            result.update(http_status=response.status, content_length=response.headers.get("Content-Length"),
                          last_modified=response.headers.get("Last-Modified"), final_url=response.geturl())
    # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
    except Exception as exc:
        # Registra/atualiza o campo 'error' em result; converte o valor para texto.
        result["error"] = str(exc)
    # Avalia a expressão de retorno abaixo e devolve esse valor ao chamador, sem criar uma nova atribuição.
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return result


# FUNÇÃO inspect_file — Recebe um recurso recente, baixa até o limite de tamanho e inspeciona schema/datas com DuckDB. Usa área de auditoria, que pode ser sobrescrita em novas execuções; não é a Bronze versionada.
def inspect_file(resource):
    # Define fmt: o formato do recurso em letras maiúsculas para comparar sem variação de caixa.
    fmt = resource["format"].upper()
    # Condição: fmt not in {'CSV', 'PARQUET'}.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if fmt not in {"CSV", "PARQUET"}:
        # Devolve o resultado ao chamador: organiza os campos em um dicionário (pares chave: valor).
        # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
        return {"status": "non_temporal_resource", "format": fmt}
    # Define target_dir: a pasta de arquivos temporais da auditoria, separada da Bronze versionada.
    target_dir = DATA_DIR / "endpoint_audit"
    # Garante a existência da pasta; parents=True cria pais ausentes e exist_ok=True aceita uma pasta já existente.
    target_dir.mkdir(parents=True, exist_ok=True)
    # Define path: o caminho local do arquivo usado nesta etapa.
    path = target_dir / (hashlib.sha256(resource["url"].encode()).hexdigest() + "." + fmt.lower())
    # Define digest: o acumulador SHA-256 ou o hash final do conteúdo, conforme a etapa.
    digest = hashlib.sha256()
    # Define size: o contador de bytes efetivamente recebidos.
    size = 0
    # Define temp: o caminho temporário terminado em .part; ainda não é um download publicado.
    temp = path.with_suffix(path.suffix + ".part")
    # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
    try:
        # Abre um contexto com request(resource['url']), temp.open('wb').
        # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
        with request(resource["url"]) as response, temp.open("wb") as output:
            # Define length: consulta uma chave com valor padrão quando ela não existe.
            length = response.headers.get("Content-Length")
            # Condição: length and int(length) > 100000000.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if length and int(length) > 100_000_000:
                # Devolve o resultado ao chamador: organiza os campos em um dicionário (pares chave: valor).
                # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
                return {"status": "size_limit", "bytes_declared": int(length)}
            # Lê o próximo bloco de bytes e repete enquanto ele não estiver vazio.
            # O operador := atribui o bloco à variável e usa esse valor como condição do laço.
            while block := response.read(1024 * 1024):
                # Atualiza size: soma o valor calculado ao conteúdo anterior.
                size += len(block)
                # Condição: size > 100000000.
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                if size > 100_000_000:
                    # Interrompe o fluxo normal com ValueError('Size limit: 100 MB'); o bloco except apropriado poderá tratar a falha.
                    raise ValueError("Size limit: 100 MB")
                # Atualiza o acumulador de hash ou os campos do dicionário, conforme o objeto antes do ponto.
                digest.update(block)
                # Grava o bloco de bytes no arquivo aberto; não interpreta nem modifica os registros.
                output.write(block)
            # Condição: length and size != int(length).
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if length and size != int(length):
                # Interrompe o fluxo normal com ValueError('Incomplete payload'); o bloco except apropriado poderá tratar a falha.
                raise ValueError("Incomplete payload")
        # Renomeia/publica o arquivo temporário no destino; se o destino existe, ele é substituído.
        temp.replace(path)
    # Finalização obrigatória: este bloco roda com sucesso, return ou exceção; é onde liberamos recursos.
    finally:
        # Remove o arquivo temporário ou redundante; missing_ok=True, quando presente, aceita que já não exista.
        temp.unlink(missing_ok=True)
    # Define con: uma conexão DuckDB local para consultas SQL, sem servidor externo.
    con = duckdb.connect(config={"threads": 1, "memory_limit": "512MB"})
    # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
    try:
        # Define relation: uma tabela consultável associada ao arquivo CSV ou Parquet.
        relation = con.read_parquet(str(path)) if fmt == "PARQUET" else con.read_csv(str(path), delimiter=";", sample_size=-1)
        # Executa a operação relation.create_view('sample'); seu efeito é descrito pela função ou pelo bloco em que aparece.
        relation.create_view("sample")
        # Define schema: a lista de nomes e tipos das colunas retornada por DESCRIBE.
        schema = con.execute("DESCRIBE sample").fetchall()
        # Define dates: o mapeamento de campos temporais e suas datas, sem modificar a origem.
        dates = {}
        # Laço: para cada elemento de schema, associa o valor a (name, datatype, *_) e executa o bloco indentado.
        for name, datatype, *_ in schema:
            # Condição: 'TIMESTAMP' in datatype or datatype == 'DATE' or re.match('^(din_|dat_|ear_data$|ena_data$)', name).
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if "TIMESTAMP" in datatype or datatype == "DATE" or re.match(r"^(din_|dat_|ear_data$|ena_data$)", name):
                # Define escaped: o nome de coluna protegido por aspas SQL para evitar erro com caracteres especiais.
                escaped = '"' + name.replace('"', '""') + '"'
                # Define parsed: a expressão SQL que tenta interpretar datas sem abortar em valores inválidos.
                parsed = f"coalesce(try_cast({escaped} AS TIMESTAMP),try_strptime(cast({escaped} AS VARCHAR), ['%Y%m%d', '%d/%m/%Y', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M']))"
                # Define values: a linha SQL com mínimo, máximo e quantidade de datas interpretáveis.
                values = con.execute(f"SELECT min({parsed}), max({parsed}), count({parsed}) FROM sample").fetchone()
                # Condição: values[2].
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                if values[2]:
                    # Registra/atualiza o campo name em dates; organiza os campos em um dicionário (pares chave: valor).
                    dates[name] = {"min": str(values[0]), "max": str(values[1]), "nonnull": values[2]}
        # Define preferred: a ordem de preferência de campos ou formatos, definida explicitamente.
        preferred = ["din_instante", "din_referenciautc", "dat_referencia", "ear_data", "ena_data", "din_data", "din_programacaodia", "dat_programacao", "din_medicao", "dat_fimsemana", "din_inicioperiodo", "din_fimperiodo"]
        # Define reference: o campo temporal selecionado como referência, ou None se não identificado.
        reference = next((name for name in preferred if name in dates), None)
        # Devolve o resultado ao chamador: organiza os campos em um dicionário (pares chave: valor).
        # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
        return {"status": "readable", "bytes": size, "sha256": digest.hexdigest(), "path": str(path),
                # Continua o dicionário: define os campos rows; cada valor vem da expressão após os dois-pontos.
                "rows": con.execute("SELECT count(*) FROM sample").fetchone()[0],
                # Continua o dicionário: define os campos date_columns, reference_column; cada valor vem da expressão após os dois-pontos.
                "date_columns": dates, "reference_column": reference,
                # Continua o dicionário: define os campos max_reference; cada valor vem da expressão após os dois-pontos.
                "max_reference": dates[reference]["max"] if reference else None,
                # Continua o dicionário: define os campos columns, name, type; cada valor vem da expressão após os dois-pontos.
                "columns": [{"name": r[0], "type": r[1]} for r in schema]}
    # Finalização obrigatória: este bloco roda com sucesso, return ou exceção; é onde liberamos recursos.
    finally:
        # Fecha a conexão/recurso aberto para liberar memória e acesso ao arquivo.
        con.close()


# FUNÇÃO audit — Recebe um conjunto CKAN, seleciona recursos recentes, testa seus links e inspeciona um formato preferido. APIs de observação são deixadas como pendentes para teste específico.
def audit(package):
    # Define result: o resultado desta operação, que será retornado, impresso ou salvo.
    result = {"dataset": package["name"], "title": package["title"], "checked_at": utcnow()}
    # Define resources: os recursos elegíveis do conjunto após os filtros.
    resources = [r for r in package.get("resources", [])
                 if str(r.get("format", "")).upper() in {"CSV", "PARQUET", "ZIP", "API"}
                 # Continua a expressão anterior: aplica a iteração ou a condição adicional indicada nesta linha.
                 and not re.search(r"dicion.rio|dictionary", str(r.get("name", "")), re.I)]
    # Define apis: os recursos marcados como API, que podem apontar para documentação Swagger.
    apis = [r for r in resources if str(r.get("format")).upper() == "API"]
    # Condição: apis.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if apis:
        # Registra/atualiza o campo 'status' em result; usa o valor literal 'api_observation_test_pending'.
        result["status"] = "api_observation_test_pending"
        # Registra/atualiza o campo 'api_descriptions' em result; percorre os elementos e aplica a transformação/filtro da compreensão.
        result["api_descriptions"] = [r.get("description") for r in apis]
        # Avalia a expressão de retorno abaixo e devolve esse valor ao chamador, sem criar uma nova atribuição.
        # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
        return result
    # Condição: not resources.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if not resources:
        # Registra/atualiza o campo 'status' em result; usa o valor literal 'no_supported_resource'.
        result["status"] = "no_supported_resource"
        # Avalia a expressão de retorno abaixo e devolve esse valor ao chamador, sem criar uma nova atribuição.
        # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
        return result
    # File-name reference wins over metadata_updated, which can refer to an old file.
    # Define newest: a maior data aproximada encontrada no nome/URL dos recursos.
    newest = max(resource_date(r) for r in resources)
    # Define candidates: os recursos da data mais recente, possivelmente em formatos alternativos.
    candidates = [r for r in resources if resource_date(r) == newest]
    # De-duplicate endpoints repeated in the catalogue.
    # Define candidates: os recursos da data mais recente, possivelmente em formatos alternativos.
    candidates = list({r["url"]: r for r in candidates}.values())
    # Registra/atualiza o campo 'latest_label_date' em result; calcula a expressão à direita antes de atribuir seu resultado.
    result["latest_label_date"] = newest
    # Registra/atualiza o campo 'endpoints' em result; percorre os elementos e aplica a transformação/filtro da compreensão.
    result["endpoints"] = [head(r) for r in candidates]
    # Define preferred: a ordem de preferência de campos ou formatos, definida explicitamente.
    preferred = sorted(candidates, key=lambda r: {"PARQUET": 0, "CSV": 1, "ZIP": 2}.get(str(r.get("format")).upper(), 3))[0]
    # Registra/atualiza o campo 'inspected_url' em result; calcula a expressão à direita antes de atribuir seu resultado.
    result["inspected_url"] = preferred["url"]
    # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
    try:
        # Registra/atualiza o campo 'content' em result; calcula a expressão à direita antes de atribuir seu resultado.
        result["content"] = inspect_file(preferred)
        # Registra/atualiza o campo 'status' em result; calcula a expressão à direita antes de atribuir seu resultado.
        result["status"] = result["content"]["status"]
    # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
    except Exception as exc:
        # Atualiza o acumulador de hash ou os campos do dicionário, conforme o objeto antes do ponto.
        result.update(status="content_error", error=str(exc))
    # Avalia a expressão de retorno abaixo e devolve esse valor ao chamador, sem criar uma nova atribuição.
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return result


# FUNÇÃO main — coordena a sequência descrita no cabeçalho deste arquivo.
# Recebe parâmetros pelo terminal ou pelos arquivos indicados; os detalhes são explicados nos blocos abaixo.
def main():
    # Define selected: os conjuntos escolhidos na configuração; pode ser ampliado por --all-details.
    selected = json.loads((ROOT / "configs/ons.json").read_text(encoding="utf-8"))["selected"]
    # Define (packages, errors): calcula a expressão à direita antes de atribuir seu resultado.
    packages, errors = [], []
    # Laço: para cada elemento de selected, associa o valor a name e executa o bloco indentado.
    for name in selected:
        # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
        try:
            # Define payload: a resposta JSON já convertida para estruturas Python.
            payload = json_get("https://dados.ons.org.br/api/3/action/package_show?id=" + name)
            # Condição: not payload.get('success').
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if not payload.get("success"):
                # Interrompe o fluxo normal com ValueError(str(payload)); o bloco except apropriado poderá tratar a falha.
                raise ValueError(str(payload))
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            packages.append(payload["result"])
        # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
        except Exception as exc:
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            errors.append({"dataset": name, "status": "catalog_error", "error": str(exc)})
    # Define result: o resultado desta operação, que será retornado, impresso ou salvo.
    result = {"started_at": utcnow(), "scope": "Newest dated resources per selected dataset; not every historical URL",
              # Continua o dicionário: define os campos results, freshness_note; cada valor vem da expressão após os dois-pontos.
              "results": errors, "freshness_note": "Reference dates are reported, not a cadence/SLA guarantee. Cadastral tables may have no operational reference date."}
    # Abre um contexto com concurrent.futures.ThreadPoolExecutor(max_workers=4).
    # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        # Define futures: percorre os elementos e aplica a transformação/filtro da compreensão.
        futures = {executor.submit(audit, p): p["name"] for p in packages}
        # Laço: para cada elemento de concurrent.futures.as_completed(futures), associa o valor a future e executa o bloco indentado.
        for future in concurrent.futures.as_completed(futures):
            # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
            try:
                # Define item: o recurso ou resultado individual sendo tratado nesta etapa.
                item = future.result()
            # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
            except Exception as exc:
                # Define item: o recurso ou resultado individual sendo tratado nesta etapa.
                item = {"dataset": futures[future], "status": "audit_error", "error": str(exc)}
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            result["results"].append(item)
            # Publica o JSON pelo helper atomic_json: escreve temporário antes de substituir o arquivo final.
            atomic_json(ROOT / "docs/inventory/endpoints_audit.json", result)
            # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
            print(json.dumps({"dataset": item["dataset"], "status": item["status"],
                              # Continua o dicionário: define os campos max_reference; cada valor vem da expressão após os dois-pontos.
                              "max_reference": item.get("content", {}).get("max_reference"),
                              # Continua o dicionário: define os campos error; cada valor vem da expressão após os dois-pontos.
                              "error": item.get("error")}, ensure_ascii=False), flush=True)
    # Registra/atualiza o campo 'completed_at' em result; obtém o instante atual em UTC.
    result["completed_at"] = utcnow()
    # Ordena a própria lista pela chave indicada, deixando a saída estável para leitura.
    result["results"].sort(key=lambda row: row["dataset"])
    # Publica o JSON pelo helper atomic_json: escreve temporário antes de substituir o arquivo final.
    atomic_json(ROOT / "docs/inventory/endpoints_audit.json", result)
    # Define lines: as linhas de texto que formarão o relatório Markdown.
    lines = ["# Auditoria dos endpoints recentes do ONS", "", f"Execução UTC: {result['completed_at']}", "",
             "Escopo: recursos de data mais recente identificados por nome/URL nos 39 conjuntos selecionados. Não testa todos os arquivos históricos.", "",
             "Datas abaixo foram lidas nos registros. Last-Modified é registrado no JSON separadamente. Ausência de data não torna cadastro inválido.", "",
             "| Dataset | Status de leitura | Maior referência nos registros | HTTP dos links recentes |", "|---|---|---|---|"]
    # Laço: para cada elemento de result['results'], associa o valor a item e executa o bloco indentado.
    for item in result["results"]:
        # Define states: o texto dos status HTTP ou erros para a tabela Markdown.
        states = ", ".join(str(e.get("http_status", e.get("error"))) for e in item.get("endpoints", []))
        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
        lines.append(f"| [{item['dataset']}](https://dados.ons.org.br/dataset/{item['dataset']}) | {item['status']} | {item.get('content', {}).get('max_reference') or 'não confirmada'} | {states or 'pendente'} |")
    # Serializa/grava o texto no caminho indicado em UTF-8; write_text substitui o conteúdo existente desse arquivo.
    (ROOT / "docs/inventory/endpoints_audit.md").write_text("\n".join(lines), encoding="utf-8")


# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == "__main__":
    # Executa a operação main(); seu efeito é descrito pela função ou pelo bloco em que aparece.
    main()
