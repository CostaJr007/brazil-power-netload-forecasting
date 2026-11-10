# GUIA DE LEITURA — Coletor central: descobre o catálogo ONS, planeja downloads e preserva arquivos brutos com auditoria.
# Entrada: argumentos do terminal e configs/ons.json. Saída: data/catalog, data/bronze e SQLite.
# Atenção: catalog, fetch, ons-load e download --execute acessam a internet; profile-csv é local.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

"""Acquisition only. Standard library; never modifies source records.

Run from the repository root: python scripts/acquire.py --help
"""
# Adia a avaliação das anotações de tipo; aqui não altera os valores manipulados pelo coletor.
from __future__ import annotations

# Importa argparse: interpreta opções do terminal, como --dataset e --execute.
import argparse
# Importa csv: lê ou escreve arquivos delimitados sem instalar dependências.
import csv
# Importa hashlib: calcula assinaturas dos bytes para identificar conteúdos.
import hashlib
# Importa json: converte entre texto JSON e estruturas Python.
import json
# Importa os: lê a variável de ambiente ENERGY_DATA_DIR.
import os
# Importa re: procura padrões de texto usando expressões regulares.
import re
# Importa sqlite3: mantém o histórico de aquisição em um banco local.
import sqlite3
# Importa sys: acessa o interpretador atual e a saída de erros.
import sys
# Importa time: permite esperar entre tentativas HTTP.
import time
# Importa uuid: gera identificadores de tentativas e arquivos temporários.
import uuid
# De datetime, importa date, datetime, timezone: representa datas, horários e UTC.
from datetime import date, datetime, timezone
# De pathlib, importa Path: constrói caminhos de arquivos de forma portátil.
from pathlib import Path
# De urllib.error, importa HTTPError, URLError: identifica erros HTTP e de conexão.
from urllib.error import HTTPError, URLError
# De urllib.parse, importa urlencode, urlsplit: codifica parâmetros e separa partes de URLs.
from urllib.parse import urlencode, urlsplit
# De urllib.request, importa Request, urlopen: faz requisições HTTP pela biblioteca padrão.
from urllib.request import Request, urlopen

# Define ROOT: a raiz do projeto: parte do caminho deste arquivo, resolve seu endereço absoluto e sobe até a pasta Energy.
ROOT = Path(__file__).resolve().parents[1]
# Pasta de dados (Bronze/Silver/Gold/estado). Padrão: <projeto>/data. Pode apontar para
# outro disco com a variável de ambiente ENERGY_DATA_DIR (ex.: D:\EnergyData\data).
DATA_DIR = Path(os.environ.get("ENERGY_DATA_DIR") or ROOT / "data")


def resolve_data_path(stored):
    """Reencontra um arquivo gravado com caminho absoluto de outra máquina/disco.

    Manifestos guardam caminhos absolutos. Se a pasta de dados mudou de lugar, o
    trecho a partir de bronze/, silver/, gold/ etc. é reaplicado sobre DATA_DIR.
    """
    path = Path(stored)
    if path.exists():
        return path
    parts = path.parts
    for anchor in ("bronze", "silver", "gold", "geography", "catalog", "runs", "weather_catalog"):
        if anchor in parts:
            candidate = DATA_DIR.joinpath(*parts[parts.index(anchor):])
            if candidate.exists():
                return candidate
    return path


# FUNÇÃO utcnow — Produz uma string com a hora atual em UTC para registrar quando uma operação aconteceu. Não recebe argumentos e não acessa arquivos.
def utcnow():
    # Avalia a expressão de retorno abaixo e devolve esse valor ao chamador, sem criar uma nova atribuição.
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return datetime.now(timezone.utc).isoformat()


# FUNÇÃO safe — Recebe um valor e devolve um nome limitado e compatível com caminhos. Essa normalização vale para nomes de pastas, não para os registros das fontes.
def safe(value):
    # Avalia a expressão de retorno abaixo e devolve esse valor ao chamador, sem criar uma nova atribuição.
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value))[:150] or "resource"


# FUNÇÃO open_http — Recebe URL e timeout; abre uma resposta HTTP. Tenta novamente apenas em falhas transitórias; o chamador deve fechar a resposta com with.
def open_http(url, timeout=60, headers=None):
    # Condição: urlsplit(url).scheme not in {'http', 'https'}.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if urlsplit(url).scheme not in {"http", "https"}:
        # Interrompe o fluxo normal com ValueError('Only HTTP(S) URLs are accepted'); o bloco except apropriado poderá tratar a falha.
        raise ValueError("Only HTTP(S) URLs are accepted")
    # Laço: para cada elemento de range(3), associa o valor a attempt e executa o bloco indentado.
    for attempt in range(3):
        # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
        try:
            # Avalia a expressão de retorno abaixo e devolve esse valor ao chamador, sem criar uma nova atribuição.
            # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
            return urlopen(Request(url, headers={"User-Agent": "EnergyDataStudy/0.2", **(headers or {})}), timeout=timeout)
        # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
        except HTTPError as exc:
            # Condição: exc.code not in {429, 500, 502, 503, 504} or attempt == 2.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                # Relança a exceção atual para que o chamador também saiba da falha; não transforma erro em sucesso.
                raise
        # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
        except (URLError, TimeoutError):
            # Condição: attempt == 2.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if attempt == 2:
                # Relança a exceção atual para que o chamador também saiba da falha; não transforma erro em sucesso.
                raise
        # Espera 1 e depois 2 segundos entre tentativas; 2 ** attempt é potência, não multiplicação.
        time.sleep(2 ** attempt)
    # Interrompe o fluxo normal com RuntimeError('HTTP retries exhausted'); o bloco except apropriado poderá tratar a falha.
    raise RuntimeError("HTTP retries exhausted")


# FUNÇÃO json_get — Recebe uma URL, usa open_http e devolve o conteúdo JSON convertido em listas/dicionários. Pode gerar exceção de rede ou de JSON inválido.
def json_get(url):
    # Abre um contexto com open_http(url).
    # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
    with open_http(url) as response:
        # Devolve o resultado ao chamador: lê e decodifica JSON diretamente de um arquivo/resposta.
        # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
        return json.load(response)


# FUNÇÃO atomic_json — Recebe caminho e objeto Python; escreve JSON temporário e só depois publica o nome final. Reduz a chance de outro leitor enxergar um arquivo incompleto; não é garantia de durabilidade contra queda de energia.
def atomic_json(path, payload):
    # Garante a existência da pasta; parents=True cria pais ausentes e exist_ok=True aceita uma pasta já existente.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Define temp: o caminho temporário terminado em .part; ainda não é um download publicado.
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    # Serializa/grava o texto no caminho indicado em UTF-8; write_text substitui o conteúdo existente desse arquivo.
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # Renomeia/publica o arquivo temporário no destino; se o destino existe, ele é substituído.
    temp.replace(path)


# FUNÇÃO digest_file — Recebe um caminho e calcula SHA-256 dos bytes em blocos. Devolve a assinatura hexadecimal sem carregar o arquivo inteiro na memória.
def digest_file(path):
    # Define digest: o acumulador SHA-256 ou o hash final do conteúdo, conforme a etapa.
    digest = hashlib.sha256()
    # Abre um contexto com path.open('rb').
    # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
    with path.open("rb") as stream:
        # Laço: para cada elemento de iter(lambda: stream.read(1024 * 1024), b''), associa o valor a block e executa o bloco indentado.
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            # Atualiza o acumulador de hash ou os campos do dicionário, conforme o objeto antes do ponto.
            digest.update(block)
    # Devolve o resultado ao chamador: converte o hash calculado em uma sequência hexadecimal legível.
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return digest.hexdigest()


# CLASSE Store — reúne conexão SQLite e gravação de arquivos. Cada objeto representa uma raiz de armazenamento.
class Store:
    # CONSTRUTOR __init__ — chamado ao criar uma instância.
    # Cria a pasta de dados, abre SQLite e garante que a tabela de tentativas exista. self guarda o estado da instância.
    def __init__(self, root):
        # Guarda o caminho raiz na instância; self permite reutilizá-lo nos outros métodos.
        self.root = Path(root)
        # Garante a existência da pasta; parents=True cria pais ausentes e exist_ok=True aceita uma pasta já existente.
        self.root.mkdir(parents=True, exist_ok=True)
        # Abre o banco SQLite local; o arquivo persistirá mesmo após encerrar o processo Python.
        self.db = sqlite3.connect(self.root / "acquisition.sqlite")
        self.db.execute("""CREATE TABLE IF NOT EXISTS attempts (
            attempt_id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT,
            source TEXT, dataset TEXT, resource_id TEXT, url TEXT,
            status TEXT, sha256 TEXT, bytes INTEGER, path TEXT, detail TEXT)""")
        # Confirma a transação SQLite para que as alterações fiquem persistidas no banco.
        self.db.commit()

    # FUNÇÃO close — Fecha a conexão SQLite que esta instância abriu. Não apaga o banco nem os dados gravados.
    def close(self):
        # Fecha a conexão/recurso aberto para liberar memória e acesso ao arquivo.
        self.db.close()

    # FUNÇÃO fetch — Recebe origem, dataset, identificador, URL e limite de bytes. Baixa os bytes, preserva revisões, registra a tentativa e devolve um manifesto. Conteúdo recebido ainda exige validação semântica.
    def fetch(self, source, dataset, resource_id, url, max_bytes=100_000_000, context=None, ranges=None):
        # ranges: lista opcional de (offset, comprimento). Usada para baixar só algumas
        # mensagens de um GRIB global (ECMWF Open Data publica um índice com esses offsets).
        # As partes são gravadas em sequência num único objeto da Bronze.
        # Define attempt_id: um UUID para distinguir esta tentativa, mesmo se o conteúdo já tiver sido baixado antes.
        attempt_id = uuid.uuid4().hex
        # Define started: o instante UTC de início desta tentativa.
        started = utcnow()
        # Define folder: a pasta da operação; no coletor, origem/dataset/recurso separam os arquivos.
        folder = self.root / "bronze" / safe(source) / safe(dataset) / safe(resource_id)
        # Garante a existência da pasta; parents=True cria pais ausentes e exist_ok=True aceita uma pasta já existente.
        folder.mkdir(parents=True, exist_ok=True)
        # Define temp: o caminho temporário terminado em .part; ainda não é um download publicado.
        temp = folder / (attempt_id + ".part")
        # Save the attempt before any I/O so interrupted executions remain visible.
        # Transação SQLite: confirma a gravação se o bloco terminar bem e desfaz em caso de exceção.
        # O with da conexão não fecha o banco; o método close faz isso.
        with self.db:
            # Executa o SQL abaixo. Placeholders ? recebem valores separados do texto SQL, quando usados; veja o guia SQL para entender a consulta.
            self.db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (attempt_id, started, None, source, dataset, resource_id,
                             url, "started", None, 0, None, None))
        # Define size: o contador de bytes efetivamente recebidos.
        size = 0
        # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
        try:
            # Abre um contexto com open_http(url), temp.open('wb').
            # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
            with temp.open("wb") as output:
                # Sem ranges há uma única requisição comum (None); com ranges, uma por parte.
                for part in (ranges or [None]):
                    extra = {"Range": f"bytes={part[0]}-{part[0] + part[1] - 1}"} if part else None
                    with (open_http(url, headers=extra) if extra else open_http(url)) as response:
                        # Servidor que ignora Range devolveria o arquivo inteiro com status 200.
                        if extra and getattr(response, "status", 206) != 206:
                            raise ValueError("Servidor ignorou o pedido de faixa de bytes (esperado HTTP 206)")
                        # Cabeçalhos e URL final da (última) resposta, para auditoria.
                        headers = dict(response.headers.items())
                        final_url = response.geturl()
                        # Tamanho anunciado pelo servidor para esta resposta; pode estar ausente.
                        expected = response.headers.get("Content-Length")
                        if expected and size + int(expected) > max_bytes:
                            raise ValueError(f"Content-Length exceeds {max_bytes} bytes")
                        received = 0
                        # Lê blocos de 1 MB até a resposta acabar; := atribui e testa ao mesmo tempo.
                        while block := response.read(1024 * 1024):
                            received += len(block)
                            size += len(block)
                            if size > max_bytes:
                                raise ValueError(f"Download exceeds {max_bytes} bytes")
                            # Grava os bytes como vieram; não interpreta nem modifica os registros.
                            output.write(block)
                        if expected and received != int(expected):
                            raise ValueError("Incomplete download (Content-Length mismatch)")
            # Condição: size == 0.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if size == 0:
                # Interrompe o fluxo normal com ValueError('Empty response'); o bloco except apropriado poderá tratar a falha.
                raise ValueError("Empty response")
            # Define prefix: um leitor binário temporário para inspecionar o começo do arquivo.
            prefix = temp.open("rb")
            # Abre um contexto com prefix.
            # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
            with prefix:
                # Define first: um pequeno prefixo dos bytes para identificar resposta HTML inesperada.
                first = prefix.read(256).lstrip().lower()
            # Condição: first.startswith((b'<!doctype html', b'<html')).
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            # Páginas de bloqueio/erro nem sempre começam com <html> (ex.: firewall da CCEE começa com <meta>).
            # Content-Type text/html também denuncia uma página no lugar do arquivo de dados.
            content_type = str(headers.get("Content-Type", "")).lower()
            if first.startswith((b"<!doctype html", b"<html", b"<meta", b"<head", b"<title", b"<body")) \
                    or content_type.startswith("text/html"):
                # Interrompe o fluxo normal com ValueError('Received HTML instead of a data file'); o bloco except apropriado poderá tratar a falha.
                raise ValueError("Received HTML instead of a data file")
            # Define digest: o acumulador SHA-256 ou o hash final do conteúdo, conforme a etapa.
            digest = digest_file(temp)
            # Content-addressed: changes create new objects, identical content reuses one.
            # Define target: o nome final baseado no hash do conteúdo, para reaproveitar bytes idênticos.
            target = folder / digest
            # Condição: target.exists().
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if target.exists():
                # Condição: digest_file(target) != digest.
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                if digest_file(target) != digest:
                    # Interrompe o fluxo normal com ValueError('Existing object failed hash verification'); o bloco except apropriado poderá tratar a falha.
                    raise ValueError("Existing object failed hash verification")
                # Remove o arquivo temporário ou redundante; missing_ok=True, quando presente, aceita que já não exista.
                temp.unlink()
                # Define status: usa o valor literal 'unchanged'.
                status = "unchanged"
            # Alternativa executada quando a condição anterior não foi atendida.
            else:
                # Renomeia/publica o arquivo temporário no destino; se o destino existe, ele é substituído.
                temp.replace(target)
                # Define status: usa o valor literal 'downloaded'.
                status = "downloaded"
            # Define metadata: o manifesto que relaciona origem, horário da coleta, hash e caminho do arquivo.
            metadata = {"attempt_id": attempt_id, "started_at": started,
                        # Continua o dicionário: define os campos ingested_at, url, final_url; cada valor vem da expressão após os dois-pontos.
                        "ingested_at": utcnow(), "url": url, "final_url": final_url,
                        # Continua o dicionário: define os campos headers, sha256, bytes; cada valor vem da expressão após os dois-pontos.
                        "headers": headers, "sha256": digest, "bytes": size,
                        # Continua o dicionário: define os campos path, source, dataset; cada valor vem da expressão após os dois-pontos.
                        "path": str(target), "source": source, "dataset": dataset,
                        # Continua o dicionário: define os campos resource_id, status; cada valor vem da expressão após os dois-pontos.
                        "resource_id": resource_id, "status": status,
                        # Continua o dicionário: define os campos context; cada valor vem da expressão após os dois-pontos.
                        "context": context or {},
                        # Continua o dicionário: define os campos note; cada valor vem da expressão após os dois-pontos.
                        "note": "HTTP Last-Modified is not a historical publication timestamp."}
            # Publica o JSON pelo helper atomic_json: escreve temporário antes de substituir o arquivo final.
            atomic_json(folder / (attempt_id + ".manifest.json"), metadata)
            # Transação SQLite: confirma a gravação se o bloco terminar bem e desfaz em caso de exceção.
            # O with da conexão não fecha o banco; o método close faz isso.
            with self.db:
                # Executa o SQL abaixo. Placeholders ? recebem valores separados do texto SQL, quando usados; veja o guia SQL para entender a consulta.
                self.db.execute("UPDATE attempts SET completed_at=?,status=?,sha256=?,bytes=?,path=? WHERE attempt_id=?",
                                (utcnow(), status, digest, size, str(target), attempt_id))
            # Avalia a expressão de retorno abaixo e devolve esse valor ao chamador, sem criar uma nova atribuição.
            # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
            return metadata
        # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
        except Exception as exc:
            # Remove o arquivo temporário ou redundante; missing_ok=True, quando presente, aceita que já não exista.
            temp.unlink(missing_ok=True)
            # Transação SQLite: confirma a gravação se o bloco terminar bem e desfaz em caso de exceção.
            # O with da conexão não fecha o banco; o método close faz isso.
            with self.db:
                # Executa o SQL abaixo. Placeholders ? recebem valores separados do texto SQL, quando usados; veja o guia SQL para entender a consulta.
                self.db.execute("UPDATE attempts SET completed_at=?,status='error',bytes=?,detail=? WHERE attempt_id=?",
                                (utcnow(), size, str(exc), attempt_id))
            # Relança a exceção atual para que o chamador também saiba da falha; não transforma erro em sucesso.
            raise


# FUNÇÃO discover — Recebe endereço CKAN e nomes selecionados. Consulta a lista de conjuntos, resolve URLs reais e devolve metadados mais erros individuais. Não baixa os arquivos de energia.
def discover(base, selected):
    # package_list inventories all names without pagination drift; package_show
    # resolves actual resource URLs for the curated selection.
    # Define listing: a resposta CKAN com os nomes dos conjuntos disponíveis.
    listing = json_get(base + "package_list")
    # Condição: not listing.get('success').
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if not listing.get("success"):
        # Interrompe o fluxo normal com RuntimeError('CKAN package_list failed'); o bloco except apropriado poderá tratar a falha.
        raise RuntimeError("CKAN package_list failed")
    # Define names: os nomes encontrados; o significado exato vem da expressão à direita.
    names = sorted(listing["result"])
    # Define (packages, errors): calcula a expressão à direita antes de atribuir seu resultado.
    packages, errors = [], []
    # Laço: para cada elemento de selected, associa o valor a name e executa o bloco indentado.
    for name in selected:
        # Condição: name not in names.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if name not in names:
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            errors.append({"dataset": name, "error": "Not found in package_list"})
            # Ignora o restante desta iteração e passa ao próximo item do laço.
            continue
        # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
        try:
            # Define payload: a resposta JSON já convertida para estruturas Python.
            payload = json_get(base + "package_show?" + urlencode({"id": name}))
            # Condição: not payload.get('success').
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if not payload.get("success"):
                # Interrompe o fluxo normal com ValueError(str(payload.get('error'))); o bloco except apropriado poderá tratar a falha.
                raise ValueError(str(payload.get("error")))
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            packages.append(payload["result"])
        # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
        except Exception as exc:
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            errors.append({"dataset": name, "error": str(exc)})
    # Devolve o resultado ao chamador: organiza os campos em um dicionário (pares chave: valor).
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return {"discovered_at": utcnow(), "method": "CKAN package_list + package_show",
            # Continua o dicionário: define os campos all_dataset_names, packages, errors; cada valor vem da expressão após os dois-pontos.
            "all_dataset_names": names, "packages": packages, "errors": errors}


# FUNÇÃO resource_plan — Recebe catálogo e filtros. Devolve uma lista ordenada de recursos elegíveis; não acessa a rede. Dicionários e arquivos de dados são selecionados separadamente.
def resource_plan(catalog, datasets, fmt, contains, documents):
    # Define rows: uma lista de registros montados em memória.
    rows = []
    # Laço: para cada elemento de catalog['packages'], associa o valor a package e executa o bloco indentado.
    for package in catalog["packages"]:
        # Condição: package['name'] not in datasets.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if package["name"] not in datasets:
            # Ignora o restante desta iteração e passa ao próximo item do laço.
            continue
        # Laço: para cada elemento de package.get('resources', []), associa o valor a item e executa o bloco indentado.
        for item in package.get("resources", []):
            # Define label: o nome legível do recurso ou a descrição usada no relatório.
            label = str(item.get("name", ""))
            # Define url: o endereço a consultar, usando metadados ou parâmetros explícitos.
            url = item.get("url", "")
            # Define is_document: se o nome do recurso indica dicionário, distinguindo documentação e dados.
            is_document = bool(re.search(r"dicion.rio|dicionario|dictionary", label, re.I))
            # Condição: documents != is_document.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if documents != is_document:
                # Ignora o restante desta iteração e passa ao próximo item do laço.
                continue
            # Condição: fmt and str(item.get('format', '')).lower() != fmt.lower().
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if fmt and str(item.get("format", "")).lower() != fmt.lower():
                # Ignora o restante desta iteração e passa ao próximo item do laço.
                continue
            # Condição: contains and contains.casefold() not in (label + ' ' + url).casefold().
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if contains and contains.casefold() not in (label + " " + url).casefold():
                # Ignora o restante desta iteração e passa ao próximo item do laço.
                continue
            # Condição: urlsplit(url).scheme not in {'http', 'https'}.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if urlsplit(url).scheme not in {"http", "https"}:
                # Ignora o restante desta iteração e passa ao próximo item do laço.
                continue
            # An API-labelled catalogue entry can point to Swagger, not observations.
            # Condição: str(item.get('format', '')).upper() == 'API'.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if str(item.get("format", "")).upper() == "API":
                # Ignora o restante desta iteração e passa ao próximo item do laço.
                continue
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            rows.append({"dataset": package["name"], "resource_id": item["id"],
                         # Continua o dicionário: define os campos name, format, url; cada valor vem da expressão após os dois-pontos.
                         "name": label, "format": item.get("format"), "url": url})
    # Devolve o resultado ao chamador: ordena os elementos segundo a chave indicada.
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return sorted(rows, key=lambda row: (row["dataset"], row["name"], row["resource_id"]))


# FUNÇÃO profile_csv — Recebe CSV local e colunas de chave. Conta linhas, células vazias, linhas malformadas e repetições da chave. A leitura preserva strings como 01 e não limpa a origem.
def profile_csv(path, keys):
    # Full scan, source strings retained; no imputation, truncation or casting.
    # Abre um contexto com Path(path).open(encoding='utf-8-sig', newline='').
    # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        # Define sample: uma amostra textual para reconhecer o delimitador do CSV.
        sample = stream.read(65536)
        # Reposiciona o leitor no início: a amostra já foi lida, mas a contagem precisa percorrer também as primeiras linhas.
        stream.seek(0)
        # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
        try:
            # Define dialect: as regras de separação reconhecidas no CSV.
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
        except csv.Error:
            # Interrompe o fluxo normal com ValueError('Delimiter uncertain; inspect source dictionary'); o bloco except apropriado poderá tratar a falha.
            raise ValueError("Delimiter uncertain; inspect source dictionary") from None
        # Define reader: o leitor CSV que devolve cada registro como dicionário.
        reader = csv.DictReader(stream, dialect=dialect)
        # Define columns: os nomes das colunas que serão lidas ou exportadas.
        columns = reader.fieldnames or []
        # Condição: not columns or len(columns) != len(set(columns)).
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if not columns or len(columns) != len(set(columns)):
            # Interrompe o fluxo normal com ValueError('Empty or duplicate column names'); o bloco except apropriado poderá tratar a falha.
            raise ValueError("Empty or duplicate column names")
        # Condição: set(keys) - set(columns).
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if set(keys) - set(columns):
            # Interrompe o fluxo normal com ValueError('Requested keys absent from CSV'); o bloco except apropriado poderá tratar a falha.
            raise ValueError("Requested keys absent from CSV")
        # Define missing: contadores de campos vazios por coluna, inicialmente zerados.
        missing = dict.fromkeys(columns, 0)
        # Define (seen, duplicates, malformed, count): calcula a expressão à direita antes de atribuir seu resultado.
        seen, duplicates, malformed, count = set(), 0, 0, 0
        # Laço: para cada elemento de reader, associa o valor a row e executa o bloco indentado.
        for row in reader:
            # Atualiza count: soma o valor calculado ao conteúdo anterior.
            count += 1
            # Atualiza malformed: soma o valor calculado ao conteúdo anterior.
            malformed += int(None in row or any(row.get(c) is None for c in columns))
            # Laço: para cada elemento de columns, associa o valor a column e executa o bloco indentado.
            for column in columns:
                # Atualiza missing[column]: soma o valor calculado ao conteúdo anterior.
                missing[column] += int(row.get(column) in {None, ""})
            # Condição: keys.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if keys:
                # Define key: a tupla dos valores das colunas escolhidas como chave.
                key = tuple(row.get(k) for k in keys)
                # Atualiza duplicates: soma o valor calculado ao conteúdo anterior.
                duplicates += int(key in seen)
                # Executa a operação seen.add(key); seu efeito é descrito pela função ou pelo bloco em que aparece.
                seen.add(key)
    # Devolve o resultado ao chamador: organiza os campos em um dicionário (pares chave: valor).
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return {"path": str(path), "sha256": digest_file(Path(path)), "rows": count,
            # Continua o dicionário: define os campos columns, delimiter, empty_cells; cada valor vem da expressão após os dois-pontos.
            "columns": columns, "delimiter": dialect.delimiter, "empty_cells": missing,
            # Continua o dicionário: define os campos malformed_rows, key_columns; cada valor vem da expressão após os dois-pontos.
            "malformed_rows": malformed, "key_columns": keys,
            # Continua o dicionário: define os campos duplicate_keys; cada valor vem da expressão após os dois-pontos.
            "duplicate_keys": duplicates if keys else None,
            # Continua o dicionário: define os campos limitations; cada valor vem da expressão após os dois-pontos.
            "limitations": "No physical bounds, timestamp coverage or business keys inferred. Empty means literal empty string only."}


# FUNÇÃO gfs_url — Recebe data, ciclo UTC, horizonte e retângulo oeste/sul/leste/norte. Valida os parâmetros e devolve uma URL NOAA; construir a URL não garante que a rodada ainda esteja disponível.
def gfs_url(day, cycle, lead, bbox):
    # Executa a operação date.fromisoformat(day); seu efeito é descrito pela função ou pelo bloco em que aparece.
    date.fromisoformat(day)
    # Condição: cycle not in {0, 6, 12, 18} or not 0 <= lead <= 384.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if cycle not in {0, 6, 12, 18} or not 0 <= lead <= 384:
        # Interrompe o fluxo normal com ValueError('Invalid cycle or lead time'); o bloco except apropriado poderá tratar a falha.
        raise ValueError("Invalid cycle or lead time")
    # Define (west, south, east, north): calcula a expressão à direita antes de atribuir seu resultado.
    west, south, east, north = bbox
    # Condição: not (-180 <= west < east <= 180 and -90 <= south < north <= 90).
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        # Interrompe o fluxo normal com ValueError('Expected bbox WEST SOUTH EAST NORTH in degrees'); o bloco except apropriado poderá tratar a falha.
        raise ValueError("Expected bbox WEST SOUTH EAST NORTH in degrees")
    # Define params: o dicionário de parâmetros que será codificado na URL do GFS.
    params = {"file": f"gfs.t{cycle:02d}z.pgrb2.0p25.f{lead:03d}",
              # Continua o dicionário: define os campos dir; cada valor vem da expressão após os dois-pontos.
              "dir": f"/gfs.{day.replace('-', '')}/{cycle:02d}/atmos",
              # Continua o dicionário: define os campos subregion, leftlon, rightlon; cada valor vem da expressão após os dois-pontos.
              "subregion": "", "leftlon": west, "rightlon": east,
              # Continua o dicionário: define os campos bottomlat, toplat; cada valor vem da expressão após os dois-pontos.
              "bottomlat": south, "toplat": north,
              # Continua o dicionário: define os campos var_UGRD, var_VGRD, var_TMP; cada valor vem da expressão após os dois-pontos.
              "var_UGRD": "on", "var_VGRD": "on", "var_TMP": "on",
              # Continua o dicionário: define os campos var_PRES, var_APCP, var_DSWRF; cada valor vem da expressão após os dois-pontos.
              "var_PRES": "on", "var_APCP": "on", "var_DSWRF": "on",
              # Continua o dicionário: define os campos lev_100_m_above_ground, lev_10_m_above_ground; cada valor vem da expressão após os dois-pontos.
              "lev_100_m_above_ground": "on", "lev_10_m_above_ground": "on",
              # Continua o dicionário: define os campos lev_2_m_above_ground, lev_surface; cada valor vem da expressão após os dois-pontos.
              "lev_2_m_above_ground": "on", "lev_surface": "on"}
    # Avalia a expressão de retorno abaixo e devolve esse valor ao chamador, sem criar uma nova atribuição.
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?" + urlencode(params)


# FUNÇÃO main — coordena a sequência descrita no cabeçalho deste arquivo.
# Recebe parâmetros pelo terminal ou pelos arquivos indicados; os detalhes são explicados nos blocos abaixo.
def main():
    # Define parser: o interpretador dos argumentos da linha de comando.
    parser = argparse.ArgumentParser(description=__doc__)
    # Configura '--data-dir': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    # Define commands: o grupo de subcomandos aceitos pelo coletor.
    commands = parser.add_subparsers(dest="command", required=True)
    # Registra o subcomando cat no interpretador do terminal e guarda sua configuração.
    cat = commands.add_parser("catalog", help="Discover ONS datasets and resource URLs")
    # Configura '--config': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    cat.add_argument("--config", type=Path, default=ROOT / "configs/ons.json")
    # Configura '--all-details': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    cat.add_argument("--all-details", action="store_true", help="Resolve every dataset, not only curated ones")
    # Registra o subcomando dl no interpretador do terminal e guarda sua configuração.
    dl = commands.add_parser("download", help="Preview selected ONS resources; --execute downloads")
    # Configura '--dataset': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    dl.add_argument("--dataset", action="append", required=True)
    # Configura '--format': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    dl.add_argument("--format", default="CSV")
    # Configura '--contains': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    dl.add_argument("--contains", default="")
    # Configura '--documents': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    dl.add_argument("--documents", action="store_true")
    # Configura '--limit': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    dl.add_argument("--limit", type=int, default=1, help="Max files TOTAL; no implicit bulk history")
    # Configura '--max-mb': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    dl.add_argument("--max-mb", type=int, default=100)
    # Configura '--execute': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    dl.add_argument("--execute", action="store_true")
    # Registra o subcomando fetch no interpretador do terminal e guarda sua configuração.
    fetch = commands.add_parser("fetch", help="Download an explicit public URL (incl. API JSON)")
    # Configura '--url': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    fetch.add_argument("--url", required=True)
    # Configura '--source': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    fetch.add_argument("--source", required=True)
    # Configura '--dataset': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    fetch.add_argument("--dataset", required=True)
    # Configura '--resource-id': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    fetch.add_argument("--resource-id", required=True)
    # Configura '--max-mb': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    fetch.add_argument("--max-mb", type=int, default=100)
    # Registra o subcomando profile no interpretador do terminal e guarda sua configuração.
    profile = commands.add_parser("profile-csv")
    # Configura 'path': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    profile.add_argument("path", type=Path)
    # Configura '--key': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    profile.add_argument("--key", action="append", default=[])
    # Registra o subcomando gfs no interpretador do terminal e guarda sua configuração.
    gfs = commands.add_parser("gfs", help="Preview a NOAA rectangular subset; --execute downloads")
    # Configura '--date': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    gfs.add_argument("--date", required=True)
    # Configura '--cycle': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    gfs.add_argument("--cycle", type=int, required=True)
    # Configura '--lead': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    gfs.add_argument("--lead", type=int, required=True)
    # Configura '--bbox': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    gfs.add_argument("--bbox", type=float, nargs=4, required=True)
    # Configura '--execute': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    gfs.add_argument("--execute", action="store_true")
    # Registra o subcomando load no interpretador do terminal e guarda sua configuração.
    load = commands.add_parser("ons-load", help="Fetch one daily window of ONS load API JSON; area code from source required")
    # Configura '--kind': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    load.add_argument("--kind", choices=["programada", "verificada"], required=True)
    # Configura '--date': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    load.add_argument("--date", required=True)
    # Configura '--area': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    load.add_argument("--area", required=True, help="Official cod_areacarga; not inferred from subsystem")
    # Define args: as opções do terminal já interpretadas, acessíveis como args.dataset etc..
    args = parser.parse_args()
    # Condição: args.command == 'catalog'.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if args.command == "catalog":
        # Define config: a configuração carregada de JSON.
        config = json.loads(args.config.read_text(encoding="utf-8"))
        # Define selected: os conjuntos escolhidos na configuração; pode ser ampliado por --all-details.
        selected = config["selected"]
        # Condição: args.all_details.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if args.all_details:
            # Define selected: os conjuntos escolhidos na configuração; pode ser ampliado por --all-details.
            selected = json_get(config["catalog_url"] + "package_list")["result"]
        # Define result: o resultado desta operação, que será retornado, impresso ou salvo.
        result = discover(config["catalog_url"], selected)
        # Define stamp: um identificador temporal UTC para preservar o snapshot do catálogo.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        # Publica o JSON pelo helper atomic_json: escreve temporário antes de substituir o arquivo final.
        atomic_json(args.data_dir / "catalog" / (stamp + ".json"), result)
        # Publica o JSON pelo helper atomic_json: escreve temporário antes de substituir o arquivo final.
        atomic_json(args.data_dir / "catalog" / "latest.json", result)
        # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
        print(json.dumps({"all_datasets": len(result["all_dataset_names"]),
                          # Continua o dicionário: define os campos resolved, errors; cada valor vem da expressão após os dois-pontos.
                          "resolved": len(result["packages"]), "errors": result["errors"]}, ensure_ascii=False))
        # Devolve o resultado ao chamador: converte para inteiro (True vira 1 e False vira 0).
        # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
        return int(bool(result["errors"]))
    # Condição: args.command == 'profile-csv'.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if args.command == "profile-csv":
        # Define result: o resultado desta operação, que será retornado, impresso ou salvo.
        result = profile_csv(args.path, args.key)
        # Define output: o objeto/caminho de saída ou arquivo aberto para escrita, conforme este bloco.
        output = args.data_dir / "reports" / (result["sha256"] + ".profile.json")
        # Publica o JSON pelo helper atomic_json: escreve temporário antes de substituir o arquivo final.
        atomic_json(output, result)
        # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
        print(json.dumps(result, ensure_ascii=False))
        # Devolve o resultado ao chamador: usa o valor literal 0.
        # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
        return 0
    # Define store: a instância responsável por salvar arquivos e registrar as tentativas.
    store = Store(args.data_dir)
    # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
    try:
        # Condição: args.command == 'ons-load'.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if args.command == "ons-load":
            # Executa a operação date.fromisoformat(args.date); seu efeito é descrito pela função ou pelo bloco em que aparece.
            date.fromisoformat(args.date)
            # Define url: o endereço a consultar, usando metadados ou parâmetros explícitos.
            url = f"https://apicarga.ons.org.br/prd/carga{args.kind}?" + urlencode(
                {"dat_inicio": args.date, "dat_fim": args.date, "cod_areacarga": args.area})
            # Define item: o recurso ou resultado individual sendo tratado nesta etapa.
            item = store.fetch("ons", f"carga-energia-{args.kind}",
                               f"{args.area}_{args.date}", url,
                               context={"area": args.area, "date": args.date,
                                        # Continua o dicionário: define os campos semantic_validation; cada valor vem da expressão após os dois-pontos.
                                        "semantic_validation": "pending: inspect JSON envelope and source documentation"})
            # Define payload: a resposta JSON já convertida para estruturas Python.
            payload = json.loads(Path(item["path"]).read_text(encoding="utf-8-sig"))
            # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
            print(json.dumps({"manifest": item, "json_type": type(payload).__name__,
                              # Continua o dicionário: define os campos note; cada valor vem da expressão após os dois-pontos.
                              "note": "HTTP 200 / valid JSON alone do not establish observation completeness."}))
            # Devolve o resultado ao chamador: usa o valor literal 0.
            # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
            return 0
        # Condição: args.command == 'download'.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if args.command == "download":
            # Condição: args.limit < 1 or args.max_mb < 1.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if args.limit < 1 or args.max_mb < 1:
                # Interrompe o fluxo normal com ValueError('limit and max-mb must be positive'); o bloco except apropriado poderá tratar a falha.
                raise ValueError("limit and max-mb must be positive")
            # Define catalog: o catálogo local, que descreve fontes e URLs, não contém os registros de energia.
            catalog = json.loads((args.data_dir / "catalog/latest.json").read_text(encoding="utf-8"))
            # Define known: o conjunto de slugs já resolvidos no catálogo.
            known = {p["name"] for p in catalog["packages"]}
            # Condição: set(args.dataset) - known.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if set(args.dataset) - known:
                # Interrompe o fluxo normal com ValueError('Dataset not resolved in catalog; run catalog first'); o bloco except apropriado poderá tratar a falha.
                raise ValueError("Dataset not resolved in catalog; run catalog first")
            # Define plan: a lista de recursos que passou pelos filtros; ainda não significa download.
            plan = resource_plan(catalog, args.dataset, args.format, args.contains, args.documents)
            # Condição: not plan.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if not plan:
                # Interrompe o fluxo normal com ValueError('No resource matches filters; inspect catalog'); o bloco except apropriado poderá tratar a falha.
                raise ValueError("No resource matches filters; inspect catalog")
            # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
            print(json.dumps({"matched": len(plan), "selected": plan[:args.limit]}, ensure_ascii=False))
            # Define failures: o contador de downloads que falharam durante o lote.
            failures = 0
            # Condição: args.execute.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if args.execute:
                # Laço: para cada elemento de plan[:args.limit], associa o valor a item e executa o bloco indentado.
                for item in plan[:args.limit]:
                    # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
                    try:
                        # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
                        print(json.dumps(store.fetch("ons", item["dataset"], item["resource_id"], item["url"], args.max_mb * 1_000_000, item)))
                    # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
                    except Exception as exc:
                        # Atualiza failures: soma o valor calculado ao conteúdo anterior.
                        failures += 1
                        # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
                        print(f"ERROR {item['resource_id']}: {exc}", file=sys.stderr)
            # Devolve o resultado ao chamador: converte para inteiro (True vira 1 e False vira 0).
            # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
            return int(bool(failures))
        # Condição: args.command == 'gfs'.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if args.command == "gfs":
            # Define url: o endereço a consultar, usando metadados ou parâmetros explícitos.
            url = gfs_url(args.date, args.cycle, args.lead, args.bbox)
            # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
            print(url)
            # Condição: args.execute.
            # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
            if args.execute:
                # Define item: o recurso ou resultado individual sendo tratado nesta etapa.
                item = store.fetch("noaa", "gfs", f"{args.date}_{args.cycle:02d}_f{args.lead:03d}", url,
                                   context={"bbox": args.bbox, "run_date": args.date,
                                            # Continua o dicionário: define os campos cycle_utc, lead_hours; cada valor vem da expressão após os dois-pontos.
                                            "cycle_utc": args.cycle, "lead_hours": args.lead,
                                            # Continua o dicionário: define os campos geometry; cada valor vem da expressão após os dois-pontos.
                                            "geometry": "rectangle, not a basin polygon"})
                # Abre um contexto com Path(item['path']).open('rb').
                # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
                with Path(item["path"]).open("rb") as stream:
                    # Condição: stream.read(4) != b'GRIB'.
                    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                    if stream.read(4) != b"GRIB":
                        # Interrompe o fluxo normal com ValueError('NOAA response is not GRIB; inspect manifest before use'); o bloco except apropriado poderá tratar a falha.
                        raise ValueError("NOAA response is not GRIB; inspect manifest before use")
                # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
                print(json.dumps(item))
            # Devolve o resultado ao chamador: usa o valor literal 0.
            # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
            return 0
        # Condição: args.max_mb < 1.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if args.max_mb < 1:
            # Interrompe o fluxo normal com ValueError('max-mb must be positive'); o bloco except apropriado poderá tratar a falha.
            raise ValueError("max-mb must be positive")
        # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
        print(json.dumps(store.fetch(args.source, args.dataset, args.resource_id, args.url, args.max_mb * 1_000_000)))
        # Devolve o resultado ao chamador: usa o valor literal 0.
        # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
        return 0
    # Finalização obrigatória: este bloco roda com sucesso, return ou exceção; é onde liberamos recursos.
    finally:
        # Fecha a conexão/recurso aberto para liberar memória e acesso ao arquivo.
        store.close()


# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == "__main__":
    # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
    try:
        # Encerra o processo com o código retornado: 0 indica sucesso; valor diferente indica falha ao terminal/agendador.
        raise SystemExit(main())
    # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
    except (OSError, ValueError, RuntimeError) as error:
        # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
        print(f"ERROR: {error}", file=sys.stderr)
        # Encerra o processo com o código retornado: 0 indica sucesso; valor diferente indica falha ao terminal/agendador.
        raise SystemExit(1)
