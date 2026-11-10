# Configurações

`ons.json` contém:

- `catalog_url`: base da API CKAN para metadados.
- `selected`: slugs oficiais que delimitam a seleção inicial.

O slug é o identificador textual do conjunto, como `balanco-energia-subsistema`. Ele não é necessariamente o nome da pasta S3. A URL de download vem dos recursos do catálogo.

`meteorology.json` registra fontes, tipo de produto, forma de acesso, estado da implementação e cuidados de qualidade. É um inventário de planejamento; não significa que todos os conectores já foram executados.

JSON não aceita comentários `#` como Python. Este README explica os campos sem quebrar o formato lido pelos scripts. Não guardar senhas ou tokens nestes arquivos.

`pipeline.json` define frequências, intervalo de revisão e limite de rejeição. Essas frequências são decisões do projeto, não promessas de atualização das fontes. `ons_contracts.json` contém 36 contratos iniciais: colunas obrigatórias, campos numéricos e campo de referência. Se o schema mudar, revisar o contrato antes de aceitar a alteração automaticamente.
