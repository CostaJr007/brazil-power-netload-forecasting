# GUIA DE LEITURA — Baixa e verifica oito amostras oficiais para demonstrar que aquisição e leitura funcionam.
# Entrada: catálogo local e URLs nele registradas. Saída: Bronze e acquisition_validation.json.
# Esta rotina usa rede, tem seleção limitada e não baixa todo o histórico do ONS.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

"""Small live smoke check; downloads only a bounded set, never full history."""
# Importa json: converte entre texto JSON e estruturas Python.
import json
# De pathlib, importa Path: constrói caminhos de arquivos de forma portátil.
from pathlib import Path
# De zipfile, importa ZipFile: inspeciona ZIP e verifica integridade CRC.
from zipfile import ZipFile

# De acquire, importa Store, atomic_json, profile_csv, resource_plan, utcnow: reutiliza funções do coletor central em vez de duplicar suas regras.
from acquire import DATA_DIR, Store, atomic_json, profile_csv, resource_plan, utcnow

# Define ROOT: a raiz do projeto: parte do caminho deste arquivo, resolve seu endereço absoluto e sobe até a pasta Energy.
ROOT = Path(__file__).resolve().parents[1]


# FUNÇÃO main — coordena a sequência descrita no cabeçalho deste arquivo.
# Recebe parâmetros pelo terminal ou pelos arquivos indicados; os detalhes são explicados nos blocos abaixo.
def main():
    # Define catalog: o catálogo local, que descreve fontes e URLs, não contém os registros de energia.
    catalog = json.loads((DATA_DIR / "catalog/latest.json").read_text(encoding="utf-8"))
    # Define store: a instância responsável por salvar arquivos e registrar as tentativas.
    store = Store(DATA_DIR)
    # Define evidence: o documento que acumula evidências das amostras verificadas.
    evidence = {"checked_at": utcnow(), "checks": [], "errors": []}
    # Define checks: a lista fixa de oito amostras: dataset, formato, filtro e indicação de dicionário.
    checks = [("balanco-energia-subsistema", "CSV", "2025", False),
              ("balanco-energia-subsistema", "PARQUET", "2025", False),
              ("ear-diario-por-subsistema", "CSV", "2025", False),
              ("ena-diario-por-subsistema", "CSV", "2025", False),
              ("bacia_contorno", "ZIP", "", False),
              ("programacao_diaria", "JSON", "", True),
              ("carga-energia-programada", "JSON", "", True),
              ("carga-energia-verificada", "JSON", "", True)]
    # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
    try:
        # Laço: para cada elemento de checks, associa o valor a (dataset, fmt, contains, docs) e executa o bloco indentado.
        for dataset, fmt, contains, docs in checks:
            # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
            try:
                # Define plan: a lista de recursos que passou pelos filtros; ainda não significa download.
                plan = resource_plan(catalog, [dataset], fmt, contains, docs)
                # Condição: not plan.
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                if not plan:
                    # Interrompe o fluxo normal com ValueError('No catalogue resource found'); o bloco except apropriado poderá tratar a falha.
                    raise ValueError("No catalogue resource found")
                # Define item: o recurso ou resultado individual sendo tratado nesta etapa.
                item = plan[0]
                # Define meta: o manifesto devolvido pelo download, incluindo o caminho dos bytes salvos.
                meta = store.fetch("ons", dataset, item["resource_id"], item["url"], context=item)
                # Define entry: a evidência de uma amostra, que será acrescentada ao relatório.
                entry = {"dataset": dataset, "format": fmt, "manifest": meta}
                # Condição: fmt == 'CSV'.
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                if fmt == "CSV":
                    # Registra/atualiza o campo 'profile' em entry; inspeciona o CSV sem alterar sua origem.
                    entry["profile"] = profile_csv(meta["path"], [])
                # Condição: fmt == 'ZIP'.
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                elif fmt == "ZIP":
                    # Abre um contexto com ZipFile(meta['path']).
                    # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
                    with ZipFile(meta["path"]) as archive:
                        # Registra/atualiza o campo 'zip_members' em entry; calcula a expressão à direita antes de atribuir seu resultado.
                        entry["zip_members"] = archive.namelist()
                        # Registra/atualiza o campo 'corrupt_member' em entry; calcula a expressão à direita antes de atribuir seu resultado.
                        entry["corrupt_member"] = archive.testzip()
                # Condição: fmt == 'JSON'.
                # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
                elif fmt == "JSON":
                    # Define value: o objeto Python obtido da leitura de JSON.
                    value = json.loads(Path(meta["path"]).read_text(encoding="utf-8-sig"))
                    # Registra/atualiza o campo 'json_type' em entry; calcula a expressão à direita antes de atribuir seu resultado.
                    entry["json_type"] = type(value).__name__
                # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
                evidence["checks"].append(entry)
                # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
                print(f"OK {dataset} {fmt}", flush=True)
            # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
            except Exception as exc:
                # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
                evidence["errors"].append({"dataset": dataset, "format": fmt, "error": str(exc)})
                # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
                print(f"ERROR {dataset} {fmt}: {exc}", flush=True)
            # Publica o JSON pelo helper atomic_json: escreve temporário antes de substituir o arquivo final.
            atomic_json(ROOT / "docs/inventory/acquisition_validation.json", evidence)
    # Finalização obrigatória: este bloco roda com sucesso, return ou exceção; é onde liberamos recursos.
    finally:
        # Fecha a conexão/recurso aberto para liberar memória e acesso ao arquivo.
        store.close()
    # Devolve o resultado ao chamador: converte para inteiro (True vira 1 e False vira 0).
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return int(bool(evidence["errors"]))


# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == "__main__":
    # Encerra o processo com o código retornado: 0 indica sucesso; valor diferente indica falha ao terminal/agendador.
    raise SystemExit(main())
