# GUIA DE LEITURA — Transforma o catálogo JSON já coletado em documentação Markdown e planilha CSV de recursos.
# Entrada: data/catalog/latest.json e configs/ons.json. Saída: docs/inventory.
# Não consulta a internet e não modifica os arquivos de energia.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

"""Export audited catalogue metadata without claiming actual temporal coverage."""
# Importa csv: lê ou escreve arquivos delimitados sem instalar dependências.
import csv
# Importa json: converte entre texto JSON e estruturas Python.
import json
# De pathlib, importa Path: constrói caminhos de arquivos de forma portátil.
from pathlib import Path

# ROOT (raiz do projeto) e DATA_DIR (pasta de dados, configurável) vêm do coletor central.
from acquire import DATA_DIR, ROOT


# FUNÇÃO main — coordena a sequência descrita no cabeçalho deste arquivo.
# Recebe parâmetros pelo terminal ou pelos arquivos indicados; os detalhes são explicados nos blocos abaixo.
def main():
    # Define catalog: o catálogo local, que descreve fontes e URLs, não contém os registros de energia.
    catalog = json.loads((DATA_DIR / "catalog/latest.json").read_text(encoding="utf-8"))
    # Define selected: os conjuntos escolhidos na configuração; pode ser ampliado por --all-details.
    selected = set(json.loads((ROOT / "configs/ons.json").read_text(encoding="utf-8"))["selected"])
    # Define out: a pasta onde o inventário legível será publicado.
    out = ROOT / "docs/inventory"
    # Garante a existência da pasta; parents=True cria pais ausentes e exist_ok=True aceita uma pasta já existente.
    out.mkdir(parents=True, exist_ok=True)
    # Define columns: os nomes das colunas que serão lidas ou exportadas.
    columns = ["dataset", "resource_id", "name", "format", "url", "created",
               "last_modified", "metadata_modified", "size"]
    # Abre um contexto com (out / 'ons_resources.csv').open('w', encoding='utf-8', newline='').
    # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
    with (out / "ons_resources.csv").open("w", encoding="utf-8", newline="") as stream:
        # Define writer: o escritor CSV configurado com nomes fixos de colunas.
        writer = csv.DictWriter(stream, fieldnames=columns)
        # Escreve a linha de cabeçalho do CSV antes dos registros.
        writer.writeheader()
        # Laço: para cada elemento de catalog['packages'], associa o valor a package e executa o bloco indentado.
        for package in catalog["packages"]:
            # Laço: para cada elemento de package.get('resources', []), associa o valor a resource e executa o bloco indentado.
            for resource in package.get("resources", []):
                # Escreve um registro CSV, associando os valores aos nomes de colunas configurados.
                writer.writerow({"dataset": package["name"], **{k: resource.get(k) for k in columns if k != "dataset"}})
    # Define lines: as linhas de texto que formarão o relatório Markdown.
    lines = ["# Inventário ONS — metadados coletados pela API", "",
             f"Coleta UTC: {catalog['discovered_at']}. Conjuntos resolvidos: {len(catalog['packages'])}.", "",
             "Datas dos recursos abaixo são metadados do catálogo; não comprovam cobertura dos registros nem publicação histórica.", "",
             "Amostras efetivamente baixadas são registradas em acquisition_validation.json. Nenhum indicador de qualidade foi inferido pela reputação da fonte.", ""]
    # Laço: para cada elemento de catalog['packages'], associa o valor a p e executa o bloco indentado.
    for p in catalog["packages"]:
        # Define formats: os formatos distintos encontrados, ordenados para facilitar a leitura.
        formats = sorted({str(r.get("format", "")) for r in p.get("resources", [])})
        # Acrescenta vários elementos à lista existente; aqui compõem o relatório.
        lines.extend([f"## {p['title']}", "", f"- Slug: `{p['name']}`; seleção inicial: {'sim' if p['name'] in selected else 'não'}.",
                      f"- Fonte: https://dados.ons.org.br/dataset/{p['name']}",
                      f"- Recursos: {len(p.get('resources', []))}; formatos: {', '.join(formats)}.",
                      f"- Licença declarada: {p.get('license_title', p.get('license_id'))}.",
                      "", str(p.get("notes", "")), ""])
    # Serializa/grava o texto no caminho indicado em UTF-8; write_text substitui o conteúdo existente desse arquivo.
    (out / "ons_catalog.md").write_text("\n".join(lines), encoding="utf-8")
    # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
    print(json.dumps({"datasets": len(catalog["packages"]),
                      # Continua o dicionário: define os campos resources; cada valor vem da expressão após os dois-pontos.
                      "resources": sum(len(p.get("resources", [])) for p in catalog["packages"]),
                      # Continua o dicionário: define os campos selected, output; cada valor vem da expressão após os dois-pontos.
                      "selected": len(selected), "output": str(out)}))


# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == "__main__":
    # Executa a operação main(); seu efeito é descrito pela função ou pelo bloco em que aparece.
    main()
