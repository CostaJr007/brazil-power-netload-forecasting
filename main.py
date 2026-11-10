# GUIA DE LEITURA — Exemplo original criado pelo PyCharm; não é o ponto de entrada do pipeline.
# Serve apenas para mostrar uma função simples e a execução condicional com __name__.
# Os comandos do projeto ficam em scripts/, descritos no guia de estudo.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

# This is a sample Python script.

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.


# FUNÇÃO print_hi — Recebe um nome e imprime uma saudação. Esta função pertence ao exemplo do PyCharm, não ao coletor de dados.
def print_hi(name):
    # Use a breakpoint in the code line below to debug your script.
    # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
    print(f'Hi, {name}')  # Press Ctrl+F8 to toggle the breakpoint.


# Press the green button in the gutter to run the script.
# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == '__main__':
    # Executa a operação print_hi('PyCharm'); seu efeito é descrito pela função ou pelo bloco em que aparece.
    print_hi('PyCharm')

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
