# Guia de estudo: entendendo o projeto por dentro

Este projeto começou pela **aquisição e auditoria de dados** e agora também tem **tratamento Silver e execução recorrente**. Leia [pipeline_diario.md](pipeline_diario.md) para acompanhar a operação. Produtos Gold e modelos estatísticos continuam futuros.

Os scripts receberam comentários em português antes das instruções e dos blocos. Leia sempre: **de onde vem o valor → o que a instrução faz → para onde o resultado vai**. Uma instrução Python pode ocupar várias linhas: parênteses, listas e dicionários continuam até fechar o delimitador. Não execute uma linha de continuação isoladamente.

## 1. Mapa das pastas

| Caminho | O que contém | Por que existe |
|---|---|---|
| `configs/` | Seleção de conjuntos ONS e registro de fontes meteorológicas | Mudar a seleção sem reescrever o coletor |
| `scripts/` | Programas executáveis de aquisição, inspeção e documentação | Cada arquivo tem uma responsabilidade identificável |
| `tests/` | Verificações com respostas HTTP falsas e arquivos pequenos | Testar falhas e revisões sem depender da internet |
| `data/catalog/` | Metadados que descrevem os conjuntos e suas URLs | Descobrir a origem dos arquivos; não confundir catálogo com energia medida |
| `data/bronze/` | Arquivos originais e manifestos | Preservar a evidência recebida e suas revisões |
| `data/endpoint_audit/` | Arquivos recentes usados na inspeção de endpoints | Separar uma auditoria pontual da Bronze versionada |
| `data/acquisition.sqlite` | Banco com tentativas de aquisição | Saber o que começou, terminou, falhou ou veio igual |
| `data/silver/` | Snapshots tratados e quarentena | Consumir publicações aprovadas sem alterar a Bronze |
| `data/runs/` | Execuções e logs | Acompanhar sucesso, falha e próxima ação operacional |
| `docs/` | Arquitetura, este guia e documentação | Registrar decisões e permitir que outra pessoa entenda o projeto |
| `docs/inventory/` | Relatórios e evidências das consultas realizadas | Sustentar conclusões com URLs, datas e resultados observados |
| `.venv/` | Interpretador/bibliotecas do projeto | Isolar dependências; não editar código de terceiros para estudar este projeto |
| `.idea/` | Configurações do PyCharm | Manter ajustes do IDE; não contém o pipeline |
| `.pytest_cache/`, `__pycache__/` | Caches gerados pelas ferramentas | Melhorar execução; não são dados de energia nem arquivos escritos para estudo |

Os README das pastas explicam seus conteúdos. Dentro da Bronze, `ons/<dataset>/<resource_id>/` são subdivisões técnicas: origem → conjunto → recurso. Não há um programa diferente em cada subpasta.

Na raiz, os `requirements*.txt` declaram bibliotecas. O lock registra versões efetivamente instaladas no Windows. `.gitignore` orienta o Git a ignorar ambiente, dados locais e arquivos transitórios; ele não apaga nada.

## 2. Ordem de leitura recomendada

1. **`main.py`**: pequeno exemplo do PyCharm para reconhecer função, argumento e `__main__`. Não é o pipeline.
2. **`inventory.py`**: começa por JSON local e termina em CSV/Markdown. Não depende de rede; bom primeiro fluxo completo.
3. **`inspect_samples.py`**: mostra como arquivos viram tabelas consultáveis com SQL.
4. **`acquire.py`**: estude as funções curtas primeiro; depois `Store` e por último `main`.
5. **`validate_sources.py`**: conecta as funções do coletor para verificar amostras.
6. **`compare_formats.py`**: confere equivalência lógica entre dois formatos.
7. **`audit_endpoints.py`**: acrescenta seleção de arquivos recentes, cabeçalhos HTTP e tarefas em paralelo.
8. **`probe_load_api.py`** e **`summarize_audit.py`**: mostram a diferença entre observar uma resposta e interpretar o resultado.
9. **`plan_weather.py`**: apresenta geometria, CRS e recorte espacial.
10. **`check_environment.py`** e **`tests/test_acquisition.py`**: mostram como verificar o ambiente e o comportamento do programa.

Depois desse fluxo inicial, leia os novos coletores meteorológicos: **discover_weather.py** preserva listagens e inspeciona as bacias; **download_weather.py** baixa os arquivos e lê seus metadados; **report_weather.py** publica o resumo local e documenta limitações. Os scripts têm comentários em português. A coluna de vento a 100 m no GFS não é uma medição direta na turbina; os metadados da altura e da rodada precisam acompanhar os valores.

Para entender a execução diária, siga **configs/pipeline.json → pipeline.py → silver.py → data/silver/current.json**. `pipeline.py` decide quando coletar; `silver.py` define como tratar; `status_pipeline.py` lê os resultados. Os arquivos `.ps1` conectam esse fluxo ao Agendador do Windows. Eles não são Python, por isso usam sintaxe PowerShell e têm comentários próprios.

`scripts/README.md` informa entradas, saídas e efeitos de cada programa. Execute os comandos a partir da pasta Energy. Os comandos com download podem usar a rede; começar pelos leitores locais evita baixar de novo enquanto você aprende.

## 3. O que Python faz quando você abre um script

Python executa as instruções do arquivo de cima para baixo. `import` carrega módulos; `def` cria uma função, mas não executa seu corpo naquele momento. `class` define um tipo de objeto. Ao chamar uma função, Python entra no corpo indentado; ao encontrar `return`, devolve o resultado ao chamador.

```python
def dobro(numero):  # numero recebe o argumento enviado na chamada.
    resultado = numero * 2  # A expressão é calculada primeiro; o nome guarda o resultado.
    return resultado  # Devolve o número para quem chamou.

valor = dobro(3)  # A função roda aqui; valor passa a ser 6.
```

Em `if __name__ == "__main__":`, a condição é verdadeira quando você inicia aquele arquivo diretamente. Ao importar `acquire` em outro script, suas definições ficam disponíveis, mas seu comando principal não é executado. Isso evita iniciar downloads só por importar uma função.

Comentários começam com `#` e não executam. Textos com três aspas no começo de módulo/função são docstrings; podem ser lidos como documentação. Mensagens e nomes de campos em inglês ainda aparecem porque fazem parte das interfaces existentes.

## 4. Estruturas que aparecem no código

| Sintaxe | Como ler | Uso no projeto |
|---|---|---|
| `nome = expressão` | Calcule a expressão; associe seu resultado ao nome | Guardar URL, configuração, resultado SQL |
| `None` | Ausência de valor | Data ainda desconhecida, erro ainda não ocorrido |
| `[a, b]` | Lista ordenada | Recursos do catálogo |
| `{"campo": valor}` | Dicionário chave → valor | Manifesto JSON |
| `{a, b}` | Conjunto sem repetições | Colunas e slugs distintos |
| `(a, b)` | Tupla, sequência normalmente fixa | Chave composta subsistema + data |
| `item["url"]` | Busque a chave obrigatória; falha se ela não existir | Metadados esperados |
| `item.get("url", "")` | Busque a chave; se ausente use o padrão | Campos opcionais |
| `lista[:2]` | Pegue os primeiros dois elementos | Amostra de resposta de API |
| `for item in lista` | Repita o bloco para cada elemento | Percorrer os conjuntos selecionados |
| `[f(x) for x in itens if condição]` | Percorra, filtre e transforme | Compreensões usadas para montar planos |
| `lambda r: r["name"]` | Função curta que devolve a chave de ordenação | `sorted` e `sort` |
| `f"erro: {exc}"` | Substitua as chaves pelos valores | Mensagens e nomes de arquivo |
| `a and b`, `a or b` | Avaliação com curto-circuito | Verificações e valores padrão |
| `while bloco := resposta.read(...)` | Leia, atribua e continue enquanto houver bytes | Download em blocos |

Em Python, `and`/`or` podem devolver os próprios operandos, não apenas booleanos. Exemplo: `context or {}` usa um dicionário vazio quando `context` é `None` ou outro valor considerado falso.

`**` tem dois usos diferentes: `2 ** attempt` calcula potência; `{**outro_dicionario}` espalha campos de um dicionário em outro. Leia pelo contexto.

## 5. Caminhos, arquivos e memória

```python
ROOT = Path(__file__).resolve().parents[1]
```

Nos scripts dentro de `scripts/`: `__file__` identifica o próprio arquivo; `Path` representa seu caminho; `resolve()` obtém o caminho absoluto; `parents[0]` é `scripts/`; `parents[1]` é Energy. Isso permite localizar a raiz independentemente do diretório de onde você chamou o script.

Com `Path`, `/` junta caminhos, por exemplo `ROOT / "data" / "catalog"`. Não está fazendo divisão numérica. Em `plan_weather.py`, o caminho padrão `data/geography/...` é relativo ao diretório atual; por isso a orientação de executar da raiz continua importante.

| Modo de abertura | Significado |
|---|---|
| `rb` | Ler bytes sem decodificar texto |
| `wb` | Escrever bytes, substituindo um arquivo existente |
| `encoding="utf-8"` | Decodificar/codificar texto com esse padrão |
| `utf-8-sig` | Aceitar também um marcador BOM no início |

Uma string é texto; bytes são os valores brutos do arquivo. O download preserva bytes. O leitor CSV interpreta texto depois. JSON precisa ser decodificado para virar listas/dicionários antes de consultar campos.

`with arquivo.open(...) as stream:` garante o fechamento ao sair. Já `with self.db:` no SQLite gerencia a transação e **não fecha a conexão**. Leia o significado do contexto de cada biblioteca.

O download lê blocos de 1 MiB (`1024 * 1024`) em vez de carregar o arquivo inteiro na memória. O perfilador mantém as chaves únicas em um `set`: essa parte cresce conforme a quantidade de registros distintos.

## 6. Uma coleta de ponta a ponta

Considere `download --dataset balanco-energia-subsistema --format CSV --contains 2025 --execute`.

1. `main()` lê as opções com `argparse`.
2. Abre `data/catalog/latest.json`, que já contém as URLs descobertas.
3. `resource_plan()` percorre o catálogo e aplica os filtros.
4. O plano é ordenado por dataset/nome/ID. **Não é uma seleção automática do ano mais recente.** O filtro de período importa.
5. `--limit` limita a quantidade total de recursos. Sem `--execute`, o plano é apenas mostrado.
6. `Store.fetch()` cria uma tentativa SQLite com status `started` antes de acessar a rede.
7. O corpo HTTP vai para `.part`, respeitando o limite de tamanho.
8. São verificados tamanho, vazio e HTML inesperado; depois é calculado SHA-256.
9. Se já existe o mesmo conteúdo, o objeto é reutilizado. Se mudou, a versão anterior continua na Bronze.
10. O manifesto relaciona bytes e origem; a tentativa termina em `downloaded`, `unchanged` ou `error`.

O script ainda baixa o conteúdo para saber seu hash; `unchanged` não significa que economizou toda a transferência. Ele economiza duplicação do armazenamento e preserva rastreabilidade.

## 7. O que são classe, self e transação

Referência das principais funções de `acquire.py`:

| Função | Parâmetros | Resultado e motivo |
|---|---|---|
| utcnow | Nenhum | String UTC; separar horário da coleta da referência do dado |
| safe | value | Nome de pasta normalizado; não trata registros de energia |
| open_http | url, timeout | Resposta HTTP aberta; política de tentativas para falhas transitórias |
| json_get | url | JSON decodificado; simplifica consultas CKAN |
| atomic_json | path, payload | Gravação em disco; função não devolve valor explícito |
| digest_file | path | String SHA-256 calculada em blocos |
| Store.__init__ | self, root | Prepara instância; efeito em diretório e SQLite |
| Store.fetch | self, source, dataset, resource_id, url, max_bytes, context | Manifesto do download; arquivos e registro de tentativa |
| Store.close | self | Fecha o banco; sem apagar suas tabelas |
| discover | base, selected | Dicionário com metadados e erros por conjunto |
| resource_plan | catalog, datasets, fmt, contains, documents | Lista filtrada; não baixa conteúdo |
| profile_csv | path, keys | Métricas locais; memória das chaves cresce com a cardinalidade |
| gfs_url | day, cycle, lead, bbox | Endereço NOAA; não executa GET |
| main | Nenhum parâmetro Python; lê o terminal | Encaminha subcomandos e retorna status |

`self` é fornecido automaticamente na chamada de método: `store.close()` corresponde a executar o método na instância `store`. `context=None` e os demais valores após `=` são padrões usados quando você omite o argumento.

`Store` é uma classe que reúne operações relacionadas. `store = Store(ROOT / "data")` cria uma instância. `__init__` prepara a pasta e abre o banco. `self.root` e `self.db` pertencem àquela instância; seus métodos podem reutilizá-los.

Na auditoria SQLite, cada linha é uma **tentativa**, não uma usina. O arquivo pode já existir e ainda assim haverá uma nova tentativa, porque horário, resposta e resultado precisam ficar registrados.

Uma transação é um conjunto de alterações confirmadas juntas. Se o bloco termina com sucesso, `with self.db:` confirma; se ocorre exceção, desfaz as alterações daquele bloco. Gravação no banco e gravação no sistema de arquivos não são uma única transação: se o processo cai entre etapas, pode haver objeto salvo sem conclusão do histórico. Esse é um limite desta implementação.

## 8. HTTP, exceções e códigos de saída

- **GET:** solicita o conteúdo; **HEAD:** solicita cabeçalhos sem transferir o arquivo inteiro.
- **200:** a requisição teve resposta bem-sucedida. Pode haver JSON vazio ou mensagem de erro no corpo.
- **404:** recurso não encontrado. **403:** acesso negado. **429:** limite de requisições. **5xx:** falha do servidor.
- `Content-Length` é o tamanho anunciado do corpo, quando disponível.
- `Last-Modified` é a alteração do objeto HTTP. Não é a última data de referência dentro do arquivo.

`try` começa uma operação que pode falhar; `except` decide como registrar/tratar a exceção; `raise` propaga a falha; `finally` finaliza recursos mesmo após erro/return. Capturar uma exceção não é provar que o dado ficou válido.

No coletor central, algumas falhas transitórias têm até três tentativas. O helper `request` da auditoria é diferente: faz uma chamada com timeout e não implementa a mesma repetição.

`return 0` indica sucesso ao código que chamou a função. Para transformar isso no status do processo, aparece `raise SystemExit(main())`. Em `main()` que apenas termina sem return, Python devolve `None`; alguns scripts chamam essa função diretamente. Outros explicitam o status para permitir uso futuro em agendamento.

## 9. SQL que você precisa entender

Leia junto com [o guia SQL](sql_do_projeto.md). Python envia o texto da consulta; DuckDB ou SQLite executa a linguagem SQL. Os comandos não são operações Python sobre cada linha.

No coletor:

```sql
INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
```

Cada `?` recebe um valor da tupla enviada separadamente. A ordem deve corresponder às colunas criadas. Isso evita concatenar valores diretamente no SQL. `UPDATE ... WHERE attempt_id=?` modifica somente a tentativa com aquele ID.

Na inspeção, `create_view("sample")` dá um nome SQL ao arquivo. Essa view é local à conexão; não está enviando a tabela a um banco remoto.

```sql
SELECT id_subsistema, count(*), min(din_instante), max(din_instante)
FROM sample
GROUP BY id_subsistema
```

`count(*)` conta registros. `min`/`max` medem os extremos. `GROUP BY` calcula separadamente por subsistema. Ter um máximo recente não garante que todas as datas/entidades estejam completas.

## 10. Meteorologia e geografia

`plan_weather.py` lê geometrias e seu CRS, que explica como coordenadas representam posições no planeta. Se não houver CRS, o script falha em vez de adivinhar. `to_crs("EPSG:4326")` transforma coordenadas conhecidas em longitude/latitude.

`geometry.bounds` devolve oeste, sul, leste e norte do retângulo envolvente. Esse retângulo inclui áreas fora da bacia. Para chuva média por bacia, a etapa posterior terá de calcular interseções e pesos por área. O script atual só prepara o pedido geográfico.

Em eólica, os locais relevantes incluem parques/conjuntos, e a altura do vento precisa ficar explícita. O código GFS pede campos/níveis, mas o fato de formar uma URL não prova que cada combinação esteja disponível na rodada escolhida.

## 11. Reproduzir com segurança durante o estudo

Comece por comandos locais:

```powershell
# Só mostra opções. Não baixa dados.
.\.venv\Scripts\python.exe scripts/acquire.py --help
# Lê o catálogo local e reescreve os relatórios do inventário.
.\.venv\Scripts\python.exe scripts/preparacao/inventory.py
# Executa simulações locais de respostas e arquivos temporários.
.\.venv\Scripts\python.exe -m pytest -q tests
```

Para acompanhar no PyCharm, coloque um breakpoint clicando na margem da linha. Execute em Debug e observe Variables. Use Step Over para avançar uma instrução e Step Into para entrar numa função. Quando chegar a uma chamada de rede ou escrita, confirme o efeito no comentário antes de continuar.

Exercícios:

1. No teste do catálogo fictício, explique por que o Swagger não pode ser tratado como CSV.
2. No teste de revisões, acompanhe três chamadas e conte objetos de conteúdo versus tentativas SQLite.
3. Antes de olhar o resultado do perfilador, preveja quantas chaves repetidas e células vazias existem no CSV de teste.
4. Explique por que `N` e `N ` podem não se juntar em SQL sem uma futura regra de normalização.
5. Explique por que não podemos somar quatro subsistemas e o agregado SIN como se fossem cinco regiões independentes.
6. Explique a diferença entre hash da URL na auditoria e hash dos bytes na Bronze.

Se você consegue responder apontando a instrução correspondente no código, já está relacionando Python com decisões de engenharia de dados.
