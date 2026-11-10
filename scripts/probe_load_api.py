# GUIA DE LEITURA — Registra o comportamento das APIs de carga para uma consulta experimental fixa.
# Entrada: endpoints conhecidos e data 08/11/2026 escrita no código. Saída: JSONs da resposta e relatório.
# É um diagnóstico pontual: HTTP 200 e lista vazia não comprovam disponibilidade de observações.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

"""Probe documented load endpoints without guessing official area codes."""
# Importa json: converte entre texto JSON e estruturas Python.
import json
# De urllib.parse, importa urlencode: codifica parâmetros e separa partes de URLs.
from urllib.parse import urlencode

# De acquire, importa ROOT, atomic_json, utcnow: reutiliza funções do coletor central em vez de duplicar suas regras.
from acquire import DATA_DIR, ROOT, atomic_json, utcnow
# De audit_endpoints, importa request: reutiliza a função de requisição da auditoria.
from audit_endpoints import request


# FUNÇÃO main — coordena a sequência descrita no cabeçalho deste arquivo.
# Recebe parâmetros pelo terminal ou pelos arquivos indicados; os detalhes são explicados nos blocos abaixo.
def main():
    # Define results: a lista de resultados individuais da verificação.
    results = []
    # Laço: para cada elemento de ['programada', 'verificada'], associa o valor a kind e executa o bloco indentado.
    for kind in ["programada", "verificada"]:
        # Define url: o endereço a consultar, usando metadados ou parâmetros explícitos.
        url = f"https://apicarga.ons.org.br/prd/carga{kind}?" + urlencode({"dat_inicio": "2026-11-08", "dat_fim": "2026-11-08"})
        # Define result: o resultado desta operação, que será retornado, impresso ou salvo.
        result = {"kind": kind, "url": url, "checked_at": utcnow(),
                  # Continua o dicionário: define os campos note; cada valor vem da expressão após os dois-pontos.
                  "note": "Area omitted deliberately; no official area code was inferred."}
        # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
        try:
            # Abre um contexto com request(url).
            # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
            with request(url) as response:
                # Registra/atualiza o campo 'http_status' em result; calcula a expressão à direita antes de atribuir seu resultado.
                result["http_status"] = response.status
                # Define body: os bytes recebidos da API, limitados antes de decodificar JSON.
                body = response.read(30_000_001)
                # Condição: len(body) > 30000000.
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                if len(body) > 30_000_000:
                    # Interrompe o fluxo normal com ValueError('Response exceeds 30 MB'); o bloco except apropriado poderá tratar a falha.
                    raise ValueError("Response exceeds 30 MB")
                # Define payload: a resposta JSON já convertida para estruturas Python.
                payload = json.loads(body)
                # Registra/atualiza o campo 'json_type' em result; calcula a expressão à direita antes de atribuir seu resultado.
                result["json_type"] = type(payload).__name__
                # Publica o JSON pelo helper atomic_json: escreve temporário antes de substituir o arquivo final.
                atomic_json(DATA_DIR / f"endpoint_audit/load_{kind}.json", payload)
                # Condição: isinstance(payload, list).
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                if isinstance(payload, list):
                    # Registra/atualiza o campo 'rows' em result; conta elementos.
                    result["rows"] = len(payload)
                    # Registra/atualiza o campo 'sample' em result; calcula a expressão à direita antes de atribuir seu resultado.
                    result["sample"] = payload[:2]
                # Condição: isinstance(payload, dict).
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                elif isinstance(payload, dict):
                    # Registra/atualiza o campo 'keys' em result; calcula a expressão à direita antes de atribuir seu resultado.
                    result["keys"] = list(payload)
                    # Registra/atualiza o campo 'envelope_preview' em result; calcula a expressão à direita antes de atribuir seu resultado.
                    result["envelope_preview"] = str(payload)[:1500]
        # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
        except Exception as exc:
            # Registra/atualiza o campo 'error' em result; converte o valor para texto.
            result["error"] = str(exc)
        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
        results.append(result)
        # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
        print(json.dumps(result, ensure_ascii=False), flush=True)
        # Publica o JSON pelo helper atomic_json: escreve temporário antes de substituir o arquivo final.
        atomic_json(ROOT / "docs/inventory/load_api_probe.json", results)


# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == "__main__":
    # Executa a operação main(); seu efeito é descrito pela função ou pelo bloco em que aparece.
    main()
