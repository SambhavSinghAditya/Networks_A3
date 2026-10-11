import socket

class CustomTCPSocket:
    def __init__(self):
        self.raw_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
        self.raw_socket.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        
        self.seq_num = self._generate_initial_seq_num()
        self.ack_num = 0
        self.source_port = self._get_random_port() # 61000-65535 for client
        self.cwnd = 1460 # Initial congestion window

    def connect(self, dest_ip, dest_port):
        """
        Used by the Client (Part C).
        1. Constructs and sends a SYN packet via self.raw_socket.sendto().
        2. Waits in a loop using self.raw_socket.recvfrom() for a matching SYN-ACK.
        3. Constructs and sends an ACK packet.
        4. Transitions state to ESTABLISHED.
        """
        pass

    def accept(self, listen_port):
        """
        Used by the Server (Part D).
        1. Loops self.raw_socket.recvfrom() waiting for an incoming SYN to listen_port.
        2. Constructs and sends a SYN-ACK.
        3. Waits for the final ACK.
        4. Transitions state to ESTABLISHED and returns the client's IP/Port.
        """
        pass

    def send(self, application_data: bytes):
        """
        Used by both Client and Server.
        1. Slices application_data into chunks based on the MSS (max 1460 bytes).
        2. Wraps each chunk in a custom TCP header and IPv4 header.
        3. Sends via raw_socket and adds to an unacknowledged data buffer.
        4. Manages congestion control window (cwnd) and retransmission timeouts.
        """
        # return the number of bytes sent, so that the HTTP layer can know how much data was sent
        pass

    def recv(self, time: float=-1) -> bytes:
        """
        Used by both Client and Server.
        1. Continuously reads raw_socket.recvfrom().
        2. Filters out packets not matching the current connection (IP/Port).
        3. Validates checksums.
        4. Strips the IPv4 and TCP headers.
        5. Buffers out-of-order packets and sends cumulative ACKs.
        6. Returns the in-order payload bytes to the HTTP layer.
        """
        # if nothign return ""
        # if budget time is over, return "", if time=0, there is no time limit
        pass

    def close(self):
        """
        Used by both Client and Server.
        1. Sends a FIN packet.
        2. Waits for the peer's ACK and FIN.
        3. Sends the final ACK.
        """
        pass