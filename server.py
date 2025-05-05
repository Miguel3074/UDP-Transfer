import socket
import os
import struct
import time
import logging

# Configuração de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - SERVER - %(levelname)s - %(message)s')

# Constantes do Protocolo
HEADER_FORMAT = '!I H B' # Sequence Number (unsigned int), Checksum (unsigned short), Flags (unsigned byte)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
DATA_PAYLOAD_SIZE = 1400 # Tamanho dos dados (em bytes) que serão incluídos em cada segmento UDP enviado.
# Escolhido para evitar fragmentação IP em redes Ethernet padrão (MTU 1500 bytes, subtraindo os tamanhos típicos dos cabeçalhos IP e UDP).
BUFFER_SIZE = HEADER_SIZE + DATA_PAYLOAD_SIZE + 512 # Tamanho do buffer de recebimento (com folga)

FLAG_LAST = 0x01 # Flag para indicar o último segmento

# --- Funções Auxiliares ---
def calculate_checksum(data):
    """Calcula um checksum simples (soma dos bytes modulo 65536)."""
    s = 0
    for byte in data:
        s += byte
    return s % 65536

def send_segment(sock, addr, seq_num, data, is_last=False):
    """Monta e envia um segmento de dados."""
    checksum = calculate_checksum(data)
    flags = FLAG_LAST if is_last else 0
    header = struct.pack(HEADER_FORMAT, seq_num, checksum, flags)
    segment = header + data
    try:
        sock.sendto(segment, addr)
        # logging.debug(f"Enviado Seg {seq_num}, Size {len(data)}, Checksum {checksum}, Last: {is_last} para {addr}")
    except socket.error as e:
        logging.error(f"Erro ao enviar segmento {seq_num} para {addr}: {e}")


def handle_retransmission(sock, addr, filename, seq_num_to_resend):
    """Reenvia um segmento específico a pedido do cliente."""
    try:
        with open(filename, 'rb') as f:
            f.seek(seq_num_to_resend * DATA_PAYLOAD_SIZE)
            data = f.read(DATA_PAYLOAD_SIZE)
            if data:
                 # Precisamos saber se este segmento *era* o último originalmente
                 file_size = os.path.getsize(filename)
                 total_segments = (file_size + DATA_PAYLOAD_SIZE - 1) // DATA_PAYLOAD_SIZE
                 is_last = (seq_num_to_resend == total_segments - 1)

                 logging.info(f"Reenviando segmento {seq_num_to_resend} para {addr}")
                 send_segment(sock, addr, seq_num_to_resend, data, is_last)
            else:
                logging.warning(f"Pedido de retransmissão para segmento {seq_num_to_resend} além do fim do arquivo {filename}")

    except FileNotFoundError:
        logging.error(f"Arquivo {filename} não encontrado para retransmissão.")
    except IOError as e:
        logging.error(f"Erro de I/O ao ler {filename} para retransmissão: {e}")
    except Exception as e:
        logging.error(f"Erro inesperado ao retransmitir segmento {seq_num_to_resend}: {e}")


def start_server(host='0.0.0.0', port=9999):
    """Inicializa e executa o servidor UDP."""
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_socket.bind((host, port))
        logging.info(f"Servidor UDP escutando em {host}:{port}")
    except socket.error as e:
        logging.error(f"Falha ao fazer bind na porta {port}: {e}")
        return

    active_transfers = {} # Para rastrear qual arquivo cada cliente está baixando (simplificado)

    while True:
        try:
            logging.info("Aguardando requisições...")
            message, client_address = udp_socket.recvfrom(BUFFER_SIZE)
            message_str = message.decode('utf-8', errors='ignore').strip()
            logging.info(f"Recebido de {client_address}: {message_str[:100]}") # Log truncado

            if message_str.startswith('GET /'):
                filename_req = message_str[5:]
                logging.info(f"Cliente {client_address} requisitou o arquivo: {filename_req}")

                # Armazena o arquivo que este cliente está tentando baixar
                active_transfers[client_address] = filename_req

                try:
                    if not os.path.exists(filename_req):
                        raise FileNotFoundError("Arquivo não encontrado no servidor.")

                    file_size = os.path.getsize(filename_req)
                    if file_size == 0:
                         logging.warning(f"Arquivo {filename_req} está vazio. Enviando um único segmento vazio.")
                         send_segment(udp_socket, client_address, 0, b'', is_last=True)
                         continue # Fim para este arquivo vazio

                    logging.info(f"Iniciando transmissão de {filename_req} ({file_size} bytes) para {client_address}")
                    seq_num = 0
                    with open(filename_req, 'rb') as f:
                        while True:
                            data = f.read(DATA_PAYLOAD_SIZE)
                            if not data:
                                break # Fim do arquivo

                            # Determina se é o último segmento lido
                            is_last_segment = (f.tell() == file_size)
                            send_segment(udp_socket, client_address, seq_num, data, is_last_segment)
                            seq_num += 1
                            time.sleep(0.001) # Pequena pausa (1 milissegundo) opcionalmente adicionada para evitar sobrecarregar redes mais lentas ou sistemas com processamento limitado, dando tempo para o processamento e evitando potencial perda de pacotes devido à velocidade excessiva de envio.

                    logging.info(f"Transmissão de {filename_req} para {client_address} concluída (enviados {seq_num} segmentos).")

                except FileNotFoundError:
                    error_msg = "ERROR 404 File Not Found\n".encode('utf-8')
                    udp_socket.sendto(error_msg, client_address)
                    logging.error(f"Arquivo {filename_req} não encontrado. Enviado erro para {client_address}")
                    if client_address in active_transfers:
                        del active_transfers[client_address] # Limpa estado
                except IOError as e:
                     error_msg = f"ERROR 500 Server IO Error: {e}\n".encode('utf-8')
                     udp_socket.sendto(error_msg, client_address)
                     logging.error(f"Erro de I/O ao ler {filename_req}: {e}")
                     if client_address in active_transfers:
                        del active_transfers[client_address] # Limpa estado
                except Exception as e:
                    error_msg = f"ERROR 500 Internal Server Error\n".encode('utf-8')
                    udp_socket.sendto(error_msg, client_address)
                    logging.error(f"Erro inesperado durante transmissão para {client_address}: {e}")
                    if client_address in active_transfers:
                        del active_transfers[client_address] # Limpa estado


            elif message_str.startswith('RETRANS '):
                 if client_address not in active_transfers:
                     logging.warning(f"Recebido RETRANS de {client_address}, mas não há transferência ativa registrada.")
                     continue # Ignora se não sabemos qual arquivo

                 current_filename = active_transfers[client_address]
                 try:
                     seq_num_to_resend = int(message_str.split()[1])
                     logging.info(f"Cliente {client_address} solicitou retransmissão do segmento {seq_num_to_resend} para o arquivo {current_filename}")
                     handle_retransmission(udp_socket, client_address, current_filename, seq_num_to_resend)
                 except (ValueError, IndexError):
                     logging.warning(f"Formato inválido de RETRANS recebido de {client_address}: {message_str}")
                 except Exception as e:
                     logging.error(f"Erro ao processar RETRANS de {client_address}: {e}")

            else:
                 logging.warning(f"Mensagem desconhecida recebida de {client_address}: {message_str[:100]}")


        except socket.timeout:
             # recvfrom pode ter timeout se configurado, mas aqui não está.
             # Útil se precisássemos fazer tarefas periódicas.
             continue
        except Exception as e:
            logging.error(f"Erro fatal no loop principal do servidor: {e}", exc_info=True)
            # Considerar reiniciar o socket ou sair dependendo da gravidade

    udp_socket.close() # Normalmente não alcançado no loop infinito
    logging.info("Servidor encerrado.")


if __name__ == "__main__":
    # Exemplo: Crie um arquivo 'large_test_file.txt' com mais de 1MB
    # dd if=/dev/urandom of=large_test_file.txt bs=1M count=5 # Linux/macOS
    # fsutil file createnew large_test_file.txt 5242880 # Windows (5MB)
    start_server(port=9999)