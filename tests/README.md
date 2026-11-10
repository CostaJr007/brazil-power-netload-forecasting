# Testes do coletor

`test_acquisition.py` usa unittest e também pode ser executado pelo pytest.

Cada teste tem preparação (arquivo/resposta fictícia), ação (função do projeto) e verificação (assert). `TemporaryDirectory` isola os arquivos; `patch.object` troca a rede real por uma resposta em memória.

Os testes verificam: reaproveitamento de conteúdo idêntico, preservação de revisão, tratamento de HTML/tamanho excessivo, ausência de temporários publicados, leitura sem alterar o CSV e seleção correta de recursos.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
```

Eles não certificam a disponibilidade atual do ONS. Essa pergunta é respondida pela auditoria de endpoints, que usa rede e guarda evidências próprias.
