import socket
import os
import time

TAMANHO_PACOTE = 1024
TIMEOUT = 2  # segundos

server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_socket.bind(('localhost', 12345))

print("[Servidor] Aguardando pedidos...")

while True:
    try:
        data, client_address = server_socket.recvfrom(1024)
        server_socket.settimeout(TIMEOUT)
        nome_arquivo = data.decode()
        print(f"[Servidor] Cliente pediu o arquivo: {nome_arquivo}")

        if not os.path.exists(nome_arquivo):
            server_socket.sendto(b"ERRO: Arquivo nao encontrado", client_address)
            continue

        with open(nome_arquivo, 'rb') as f:
            seq = 0
            while True:
                chunk = f.read(TAMANHO_PACOTE - 10)  # espaço pro cabeçalho
                if not chunk:
                    break

                header = f"{seq:06d}|".encode()  # Ex: 000001|
                pacote = header + chunk
                enviado = False

                while not enviado:
                    server_socket.sendto(pacote, client_address)
                    print(f"[Servidor] Enviado pacote {seq}")

                    try:
                        ack, _ = server_socket.recvfrom(1024)
                        if ack.decode() == f"ACK|{seq}":
                            enviado = True
                            print(f"[Servidor] ACK recebido para {seq}")
                        else:
                            print(f"[Servidor] ACK incorreto: {ack}")
                    except socket.timeout:
                        print(f"[Servidor] Timeout, reenviando pacote {seq}...")

                seq += 1

        server_socket.sendto(b"FIM", client_address)
        print("[Servidor] Envio finalizado.")
        try:
            fim_ack, addr = server_socket.recvfrom(1024)
            if fim_ack.decode() == "ACK|FIM":
                print("[Servidor] Cliente confirmou recebimento do FIM.")
        except socket.timeout:
            print("[Servidor] Timeout esperando ACK do FIM.")

    except Exception as e:
        print(f"[Servidor] Erro: {e}")
