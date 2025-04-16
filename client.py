import socket

client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
client_socket.settimeout(5)

server_address = ('localhost', 12345)

nome_arquivo = "teste.txt"
client_socket.sendto(nome_arquivo.encode(), server_address)

buffer = {}

while True:
    try:
        pacote, _ = client_socket.recvfrom(1024)

        if pacote == b"FIM":
            print("[Cliente] Arquivo recebido completo.")
            break

        if pacote.startswith(b"ERRO"):
            print("[Cliente]", pacote.decode())
            break

        header, dados = pacote.split(b"|", 1)
        seq = int(header.decode())

        if seq not in buffer:
            buffer[seq] = dados
            print(f"[Cliente] Pacote {seq} recebido.")
        else:
            print(f"[Cliente] Pacote {seq} duplicado (ignorado).")

        # Envia ACK
        ack_msg = f"ACK|{seq}"
        client_socket.sendto(ack_msg.encode(), server_address)

    except socket.timeout:
        print("[Cliente] Timeout esperando pacote.")
        break

# Salva o arquivo
with open("arquivo_recebido.txt", "wb") as f:
    for seq in sorted(buffer):
        f.write(buffer[seq])

print("[Cliente] Arquivo salvo como 'arquivo_recebido.txt'")
client_socket.close()
