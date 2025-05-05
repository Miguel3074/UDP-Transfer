import socket
import struct
import time
import random
import argparse
import logging
import os

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - CLIENT - %(levelname)s - %(message)s')

# Constantes do Protocolo (devem corresponder às do servidor)
HEADER_FORMAT = '!I H B' # Sequence Number (unsigned int), Checksum (unsigned short), Flags (unsigned byte)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
BUFFER_SIZE = 65536  # Tamanho do buffer de recebimento (deve ser >= que o datagrama do servidor)

FLAG_LAST = 0x01 # Flag para indicar o último segmento

# --- Funções Auxiliares ---
def calculate_checksum(data):
    """Calcula um checksum simples (soma dos bytes modulo 65536)."""
    s = 0
    for byte in data:
        s += byte
    return s % 65536

def parse_address(addr_str):
    """Analisa 'host:port' e retorna (host, port)."""
    try:
        host, port_str = addr_str.split(':')
        port = int(port_str)
        if not (1024 < port < 65536):
            raise ValueError("Porta deve estar entre 1025 e 65535")
        return host, port
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Formato de endereço inválido '{addr_str}'. Use HOST:PORT. Erro: {e}")

# --- Função Principal do Cliente ---
def start_client(server_addr_str, filename, output_filename=None, loss_probability=0.0, timeout_seconds=10.0, max_retries=5):
    """Inicia o cliente UDP para baixar um arquivo."""

    try:
        server_host, server_port = parse_address(server_addr_str)
        server_address = (server_host, server_port)
    except argparse.ArgumentTypeError as e:
        logging.error(e)
        return

    if not output_filename:
        output_filename = f"downloaded_{os.path.basename(filename)}"

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.settimeout(timeout_seconds) # Timeout para recebimento

    # Envia a requisição inicial
    request_message = f"GET /{filename}\n".encode('utf-8')
    try:
        logging.info(f"Enviando requisição para {server_address}: GET /{filename}")
        udp_socket.sendto(request_message, server_address)
    except socket.error as e:
        logging.error(f"Erro ao enviar requisição inicial para {server_address}: {e}")
        udp_socket.close()
        return

    received_segments = {} # Dicionário para armazenar {seq_num: data}
    expected_total_segments = None # Será definido quando o último segmento chegar
    highest_seq_num_received = -1
    last_segment_received = False

    # Loop principal de recebimento
    logging.info("Aguardando segmentos do servidor...")
    while not last_segment_received:
        try:
            segment, sender_address = udp_socket.recvfrom(BUFFER_SIZE)

            if sender_address != server_address:
                logging.warning(f"Recebido pacote de endereço inesperado {sender_address}. Ignorando.")
                continue

            # Verifica se é uma mensagem de erro do servidor
            if segment.startswith(b'ERROR '):
                 error_message = segment.decode('utf-8', errors='ignore').strip()
                 logging.error(f"Erro recebido do servidor: {error_message}")
                 udp_socket.close()
                 return # Aborta o cliente

            # Processa segmento de dados
            if len(segment) < HEADER_SIZE:
                logging.warning(f"Recebido pacote muito curto ({len(segment)} bytes). Ignorando.")
                continue

            # Desempacota o cabeçalho
            header = segment[:HEADER_SIZE]
            data = segment[HEADER_SIZE:]
            seq_num, checksum_recv, flags = struct.unpack(HEADER_FORMAT, header)

            # --- Simulação de Perda ---
            if random.random() < loss_probability:
                logging.warning(f"*** SIMULANDO PERDA do segmento {seq_num} ***")
                continue # Descarta o pacote intencionalmente

            # --- Verificação de Checksum ---
            checksum_calc = calculate_checksum(data)
            if checksum_recv != checksum_calc:
                logging.error(f"Checksum inválido para segmento {seq_num}! Recebido={checksum_recv}, Calculado={checksum_calc}. Segmento descartado.")
                continue # Descarta o pacote corrompido

            # Armazena o segmento válido se ainda não o tivermos
            if seq_num not in received_segments:
                 logging.info(f"Recebido segmento {seq_num} (Size: {len(data)}, Checksum OK)")
                 received_segments[seq_num] = data
                 highest_seq_num_received = max(highest_seq_num_received, seq_num)
            else:
                 logging.debug(f"Recebido segmento duplicado {seq_num}. Ignorando.")


            # Verifica se é o último segmento
            if flags & FLAG_LAST:
                logging.info(f"Recebida flag de ÚLTIMO segmento no número {seq_num}")
                last_segment_received = True
                expected_total_segments = seq_num + 1

        except socket.timeout:
            logging.warning("Timeout ao esperar por segmentos.")
            if not received_segments:
                 logging.error("Nenhum segmento recebido do servidor. Abortando.")
                 udp_socket.close()
                 return
            # Se já recebemos algo, o timeout pode indicar o fim da rajada inicial
            # ou perda do último segmento. Saímos do loop para verificar o que falta.
            break
        except Exception as e:
            logging.error(f"Erro durante o recebimento: {e}", exc_info=True)
            # Considerar abortar ou tentar continuar? Por segurança, vamos parar.
            udp_socket.close()
            return


    # --- Fase de Verificação e Retransmissão ---
    if expected_total_segments is None and highest_seq_num_received > -1:
        # Se o último pacote (com a flag) foi perdido, mas recebemos outros
        logging.warning("Flag de último segmento não recebida. Estimando total com base no maior recebido.")
        # É uma heurística. Poderia ser N ou N+k se os últimos k se perderam.
        # Vamos pedir retransmissão do que achamos ser o último para confirmar.
        expected_total_segments = highest_seq_num_received + 1 # Suposição inicial

    elif expected_total_segments is None and highest_seq_num_received == -1:
        logging.error("Nenhum segmento válido recebido ou flag de último não chegou. Impossível continuar.")
        udp_socket.close()
        return


    retry_count = 0
    while retry_count < max_retries:
        missing_segments = []
        if expected_total_segments is not None:
            all_expected = set(range(expected_total_segments))
            received_set = set(received_segments.keys())
            missing_segments = sorted(list(all_expected - received_set))

        if not missing_segments:
            logging.info("Todos os segmentos foram recebidos com sucesso!")
            break # Saia do loop de retentativas

        logging.warning(f"Segmentos faltando: {missing_segments} (Tentativa {retry_count + 1}/{max_retries})")

        # Solicita retransmissão dos segmentos faltantes
        for seq_num_miss in missing_segments:
            retrans_req = f"RETRANS {seq_num_miss}\n".encode('utf-8')
            try:
                logging.info(f"Solicitando retransmissão do segmento {seq_num_miss}")
                udp_socket.sendto(retrans_req, server_address)
                time.sleep(0.01) # Pequena pausa entre requisições
            except socket.error as e:
                 logging.error(f"Erro ao enviar pedido RETRANS para seg {seq_num_miss}: {e}")


        # Tenta receber os segmentos retransmitidos
        receive_start_time = time.time()
        newly_received_count = 0
        while time.time() - receive_start_time < timeout_seconds * 5: # Dê mais tempo para retransmissões
             try:
                 segment, sender_address = udp_socket.recvfrom(BUFFER_SIZE)
                 if sender_address != server_address: continue

                 if len(segment) < HEADER_SIZE: continue
                 header = segment[:HEADER_SIZE]
                 data = segment[HEADER_SIZE:]
                 seq_num, checksum_recv, flags = struct.unpack(HEADER_FORMAT, header)

                 # Verificar checksum novamente
                 checksum_calc = calculate_checksum(data)
                 if checksum_recv != checksum_calc:
                     logging.error(f"[RETRANS] Checksum inválido para segmento {seq_num}. Descartado.")
                     continue

                 if seq_num in missing_segments and seq_num not in received_segments:
                     logging.info(f"[RETRANS] Recebido segmento faltante {seq_num} (Size: {len(data)}, Checksum OK)")
                     received_segments[seq_num] = data
                     highest_seq_num_received = max(highest_seq_num_received, seq_num)
                     newly_received_count += 1

                     # Se recebermos um segmento com flag LAST que não tínhamos antes
                     if flags & FLAG_LAST and expected_total_segments != (seq_num + 1):
                          logging.info(f"[RETRANS] Flag de ÚLTIMO segmento ({seq_num}) recebida/confirmada.")
                          expected_total_segments = seq_num + 1
                          # Precisamos recalcular os missing com base no novo total? Sim.
                          # Melhor sair deste loop interno e refazer a verificação completa.
                          break # Sai do loop de recebimento de retransmissões

                 # Otimização: Se recebemos todos os que pedimos nesta rodada, podemos sair mais cedo
                 # (Requer checar se 'missing_segments' agora está vazio após adicionar este)

             except socket.timeout:
                  logging.debug("[RETRANS] Timeout esperando por segmentos retransmitidos.")
                  break # Sai do loop de recebimento de retransmissões
             except Exception as e:
                  logging.error(f"[RETRANS] Erro durante recebimento de retransmissão: {e}")
                  break # Sai do loop de recebimento de retransmissões

        if newly_received_count == 0 and missing_segments:
             logging.warning("Nenhum dos segmentos retransmitidos solicitados foi recebido nesta tentativa.")

        retry_count += 1


    # --- Montagem Final do Arquivo ---
    if expected_total_segments is None:
         logging.error("Não foi possível determinar o número total de segmentos. Abortando montagem.")
         udp_socket.close()
         return

    final_missing = sorted(list(set(range(expected_total_segments)) - set(received_segments.keys())))

    if final_missing:
        logging.error(f"Falha ao receber todos os segmentos após {max_retries} tentativas. Segmentos ainda faltando: {final_missing}")
        success = False
    else:
        logging.info(f"Todos os {expected_total_segments} segmentos recebidos. Montando o arquivo: {output_filename}")
        try:
            with open(output_filename, 'wb') as f_out:
                for i in range(expected_total_segments):
                    if i in received_segments:
                        f_out.write(received_segments[i])
                    else:
                        # Isso não deveria acontecer se final_missing estava vazio, mas é uma checagem de segurança
                        logging.error(f"Erro crítico: Segmento {i} ausente durante a escrita final!")
                        raise IOError(f"Segmento {i} ausente inesperadamente.")
            logging.info(f"Arquivo {output_filename} salvo com sucesso!")
            success = True
        except IOError as e:
            logging.error(f"Erro ao escrever o arquivo de saída {output_filename}: {e}")
            success = False
        except Exception as e:
             logging.error(f"Erro inesperado ao montar o arquivo: {e}")
             success = False

    udp_socket.close()
    logging.info("Conexão do cliente fechada.")
    return success

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cliente UDP para transferência confiável de arquivos.")
    parser.add_argument("server_address", type=str, help="Endereço do servidor no formato HOST:PORT (ex: 127.0.0.1:9999)")
    parser.add_argument("filename", type=str, help="Nome do arquivo a ser requisitado do servidor.")
    parser.add_argument("-o", "--output", type=str, default="downloaded_text.txt", help="Nome do arquivo local para salvar (padrão: downloaded_<filename>)")
    parser.add_argument("-l", "--loss", type=float, default=0.1, help="Probabilidade de simular perda de pacotes recebidos (0.0 a 1.0, ex: 0.1 para 10%%)")
    parser.add_argument("-t", "--timeout", type=float, default=2.0, help="Timeout em segundos para esperar por pacotes (ex: 2.0)")
    parser.add_argument("-r", "--retries", type=int, default=5, help="Número máximo de tentativas de retransmissão (ex: 5)")

    args = parser.parse_args()

    if not (0.0 <= args.loss <= 1.0):
        print("Erro: A probabilidade de perda deve estar entre 0.0 e 1.0.")
        exit(1)

    start_client(args.server_address, args.filename, args.output, args.loss, args.timeout, args.retries)