# Transferência Confiável de Arquivos via UDP

Este projeto implementa uma transferência de arquivos confiável utilizando o protocolo UDP. Ele consiste em um servidor que envia um arquivo solicitado por um cliente, segmentando-o e adicionando mecanismos para garantir a entrega confiável, como checksums e retransmissões.

## Visão Geral

* **Servidor (server.py):** Escuta por requisições de arquivos de clientes. Ao receber uma requisição, ele lê o arquivo, o divide em segmentos, adiciona um cabeçalho com número de sequência, checksum e flags, e envia os segmentos para o cliente via UDP. Também lida com pedidos de retransmissão de segmentos perdidos.
* **Cliente (client.py):** Envia uma requisição para o servidor especificando o nome do arquivo desejado. Recebe os segmentos do servidor, verifica o checksum, lida com a entrega fora de ordem (através de um buffer de reordenação), solicita a retransmissão de segmentos perdidos e, finalmente, monta o arquivo recebido.

## Funcionalidades

* **Segmentação de Arquivos:** O servidor divide o arquivo em segmentos menores para transmissão via UDP.
* **Cabeçalho de Segmento:** Cada segmento possui um cabeçalho contendo:
    * Número de sequência: Para reordenar os segmentos no cliente.
    * Checksum: Para verificar a integridade dos dados recebidos.
    * Flags: Para indicar o último segmento da transmissão.
* **Verificação de Checksum:** O cliente verifica a integridade de cada segmento recebido usando o checksum. Segmentos corrompidos são descartados.
* **Reordenação de Segmentos:** O cliente utiliza um buffer para reordenar os segmentos recebidos fora de ordem com base no número de sequência.
* **Retransmissão de Segmentos Perdidos:** O cliente detecta segmentos faltantes e solicita sua retransmissão ao servidor.
* **Simulação de Perda de Pacotes (Cliente):** O cliente possui uma opção para simular a perda de pacotes durante o recebimento para testar a robustez do sistema de retransmissão.
* **Timeout e Retries:** O cliente implementa timeouts para esperar por segmentos e um número máximo de tentativas de retransmissão.

## Como Rodar

**Pré-requisito:** Certifique-se de ter o Python 3 instalado em seu sistema.

**Ordem de Execução:**

**1. Execute o Servidor:**

   Abra um terminal ou prompt de comando, navegue até o diretório onde você salvou o arquivo `server.py` e execute o seguinte comando:

   `python server.py`

   O servidor iniciará e exibirá uma mensagem indicando o endereço e a porta em que está escutando (por padrão, `0.0.0.0:9999`). **Mantenha esta janela do terminal aberta enquanto o cliente estiver em execução.**

**2. Execute o Cliente:**

   Abra outro terminal ou prompt de comando, navegue até o diretório onde você salvou o arquivo `client.py` e execute o comando abaixo, substituindo os argumentos conforme necessário:

   `python client.py <endereço_do_servidor>:<porta_do_servidor> <nome_do_arquivo_a_baixar> [opções]`


   **Exemplo:** Para o arquivo `text.txt` do servidor rodando na mesma máquina (localhost) na porta 9999:

   `python client.py 127.0.0.1:9999 text.txt -o downloaded_text.txt -l 0.1`

   **Opções do Cliente:**

   * `-o` ou `--output`: Nome do arquivo local para salvar o arquivo baixado (padrão: `downloaded_<nome_do_arquivo>`).
   * `-l` ou `--loss`: Probabilidade de simular perda de pacotes recebidos (valor entre 0.0 e 1.0).
   * `-t` ou `--timeout`: Timeout em segundos para esperar por pacotes (padrão: 2.0).
   * `-r` ou `--retries`: Número máximo de tentativas de retransmissão (padrão: 5).

   **Exemplo com opções:**

   `python client.py 127.0.0.1:9999 arquivo_grande.zip -o backup.zip -l 0.05 -t 5.0 -r 10`

   Este comando baixará o arquivo `arquivo_grande.zip` do servidor, salvará localmente como `backup.zip`, simulará uma perda de pacotes de 5%, definirá um timeout de 5 segundos e tentará retransmitir até 10 vezes.

## Observações

* Certifique-se de que o arquivo especificado no cliente (`<nome_do_arquivo_a_baixar>`) exista no diretório de trabalho do servidor.
* As constantes do protocolo (`HEADER_FORMAT`, `DATA_PAYLOAD_SIZE`, `FLAG_LAST`) devem ser idênticas nos arquivos `server.py` e `client.py`.
* O desempenho da transferência pode variar dependendo das condições da rede e do tamanho do arquivo.

## Próximos Passos (Melhorias Possíveis)

* Implementar controle de fluxo mais sofisticado (ex: janela deslizante).
* Adicionar mecanismos de detecção de congestionamento.
* Melhor tratamento de erros e logs mais detalhados.
* Suporte para transferências simultâneas de múltiplos clientes.