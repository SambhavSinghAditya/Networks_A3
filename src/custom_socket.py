import random
import socket
import time

import ip_header
import tcp

MY_MSS = 1460
DEFAULT_PEER_MSS = 536          # used when the peer sends no MSS option
WINDOW = 65535                  # fixed advertised window (T11)
TTL = 64
HANDSHAKE_RETRY = 1.0           # resend SYN / SYN-ACK every 1 s (T7)
HANDSHAKE_TIMEOUT = 8.0         # keep trying for more than 6 s (T7)
CLOSE_TIMEOUT = 2.0             # give up on teardown after 2 s (T9)
IDLE_TIMEOUT = 10.0             # give up if nothing is acknowledged for 10 s (T10)
MIN_RTO = 0.2
MAX_RTO = 1.0                   # retransmission timeout is at most 1 s (T10)
INITIAL_CWND = 10               # in segments

# the server creates one socket per connection, so all of them share one open log file
log_files = {}


def open_log(path):
    if path not in log_files:
        log_files[path] = open(path, "w")
    return log_files[path]


# sequence numbers wrap around at 2^32, so compare them with modular arithmetic
def seq_add(seq, n):
    return (seq + n) & 0xFFFFFFFF


def seq_diff(a, b):
    # how far a is ahead of b
    return (a - b) & 0xFFFFFFFF


def seq_lt(a, b):
    return 0 < seq_diff(b, a) < 2**31


def seq_le(a, b):
    return seq_diff(b, a) < 2**31


class CustomTCPSocket:
    def __init__(self, logfile=None):
        self.log = open_log(logfile) if logfile else None
        self.raw_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
        self.raw_socket.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        self.raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)

        self.state = "CLOSED"
        self.local_ip = None
        self.local_port = None
        self.remote_ip = None
        self.remote_port = None
        self.ip_id = random.randint(1, 65535)

        # sending side
        self.iss = random.randint(0, 2**32 - 1)     # random initial sequence number (T6)
        self.snd_una = self.iss                     # oldest unacknowledged byte
        self.snd_nxt = self.iss                     # next byte to send
        self.snd_max = self.iss                     # highest byte ever sent
        self.send_data = b""
        self.send_base = self.iss                   # sequence number of send_data[0]
        self.peer_mss = None
        self.mss = DEFAULT_PEER_MSS
        self.peer_window = WINDOW

        # congestion control (Reno with NewReno partial ACKs)
        self.cwnd = INITIAL_CWND * self.mss
        self.ssthresh = 2**30
        self.dup_acks = 0
        self.in_recovery = False
        self.recover = self.iss

        # retransmission timer
        self.rto = MAX_RTO
        self.srtt = None
        self.rttvar = 0
        self.rtt_seq = None         # an RTT sample is taken when this byte is acked
        self.rtt_time = 0
        self.timer = None
        self.last_progress = 0

        # receiving side
        self.rcv_nxt = 0
        self.recv_buffer = bytearray()
        self.out_of_order = {}      # seq -> payload
        self.peer_fin_seq = None
        self.peer_fin = False

    # ---------------- connection setup ----------------

    def connect(self, dest_ip, dest_port):
        self.remote_ip = dest_ip
        self.remote_port = dest_port
        self.local_ip = self._find_local_ip(dest_ip)
        self.local_port = random.randint(61000, 65535)     # T13

        start = time.time()
        last_sent = None
        while True:
            now = time.time()
            if now - start >= HANDSHAKE_TIMEOUT:
                raise TimeoutError("connection timed out")
            if last_sent is None or now - last_sent >= HANDSHAKE_RETRY:
                self._send_segment(tcp.SYN, self.iss, mss=MY_MSS)
                last_sent = now

            seg = self._next_segment(last_sent + HANDSHAKE_RETRY - time.time())
            if seg is None:
                continue
            flags = seg["flags"]
            if flags & tcp.RST:
                if flags & tcp.ACK and seg["ack"] == seq_add(self.iss, 1):
                    self.state = "CLOSED"
                    raise ConnectionRefusedError("connection refused")
                continue
            if flags & tcp.SYN and flags & tcp.ACK and seg["ack"] == seq_add(self.iss, 1):
                self.rcv_nxt = seq_add(seg["seq"], 1)
                self.peer_mss = seg["mss"]
                self._established(seg["window"])
                self._send_segment(tcp.ACK, self.snd_nxt)
                return

    def accept(self, listen_port):
        self.local_port = listen_port

        # wait (forever) for a SYN to our port, on any of our addresses
        while True:
            packet = self._receive_packet(None)
            if packet is None:
                continue
            ip, seg = packet
            flags = seg["flags"]
            if seg["dest_port"] == listen_port and flags & tcp.SYN and not flags & (tcp.ACK | tcp.RST):
                break

        self.remote_ip = ip["source_ip"]
        self.remote_port = seg["source_port"]
        self.local_ip = ip["dest_ip"]           # reply from the address the SYN was sent to
        self._log("RECV", ip["source_ip"], ip["dest_ip"], ip["ttl"], ip["identification"], seg)
        self.rcv_nxt = seq_add(seg["seq"], 1)
        self.peer_mss = seg["mss"]

        start = time.time()
        last_sent = None
        while True:
            now = time.time()
            if now - start >= HANDSHAKE_TIMEOUT:
                raise TimeoutError("handshake timed out")
            if last_sent is None or now - last_sent >= HANDSHAKE_RETRY:
                self._send_segment(tcp.SYN | tcp.ACK, self.iss, mss=MY_MSS)
                last_sent = now

            seg = self._next_segment(last_sent + HANDSHAKE_RETRY - time.time())
            if seg is None:
                continue
            flags = seg["flags"]
            if flags & tcp.RST:
                self.state = "CLOSED"
                raise ConnectionError("connection reset during handshake")
            if flags & tcp.SYN:
                last_sent = None            # client resent its SYN, so resend the SYN-ACK now
                continue
            if flags & tcp.ACK and seg["ack"] == seq_add(self.iss, 1):
                self._established(seg["window"])
                if seg["payload"] or flags & tcp.FIN:
                    self._handle_data(seg)
                return self.remote_ip, self.remote_port

    def _established(self, window):
        self.state = "ESTABLISHED"
        self.mss = min(MY_MSS, self.peer_mss or DEFAULT_PEER_MSS)     # T3
        self.cwnd = INITIAL_CWND * self.mss
        self.peer_window = window
        self.snd_una = seq_add(self.iss, 1)
        self.snd_nxt = self.snd_una
        self.snd_max = self.snd_una
        self.send_base = self.snd_una

    def _find_local_ip(self, dest_ip):
        # connecting a UDP socket sends nothing; it only makes the kernel pick
        # the source address it would use to reach dest_ip
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect((dest_ip, 9))
            return probe.getsockname()[0]
        finally:
            probe.close()

    # ---------------- sending data ----------------

    def send(self, data):
        # blocks until all of data is acknowledged, then returns len(data)
        if self.state != "ESTABLISHED":
            raise ConnectionError("connection is not open")
        if len(data) == 0:
            return 0

        self.send_data = bytes(data)
        self.send_base = self.snd_una
        end = seq_add(self.send_base, len(data))
        self.last_progress = time.time()

        while self.snd_una != end:
            self._send_new_data()
            now = time.time()
            if now - self.last_progress >= IDLE_TIMEOUT:
                raise TimeoutError("nothing acknowledged for 10 seconds")
            if self.timer is not None and now >= self.timer:
                self._on_timeout()
                continue

            if self.timer is not None:
                wait = self.timer - now
            else:
                wait = self.last_progress + IDLE_TIMEOUT - now
            seg = self._next_segment(wait)
            if seg is not None:
                self._handle_segment(seg)
        return len(data)

    def _send_new_data(self):
        # send as much new data as min(cwnd, peer window) allows (T10)
        while True:
            offset = seq_diff(self.snd_nxt, self.send_base)
            remaining = len(self.send_data) - offset
            if remaining <= 0:
                return
            in_flight = seq_diff(self.snd_nxt, self.snd_una)
            window = min(self.cwnd, self.peer_window)
            size = min(self.mss, remaining, window - in_flight)
            if size <= 0:
                return

            # time one segment at a time, and never a retransmitted one (Karn)
            if self.rtt_seq is None and self.snd_nxt == self.snd_max:
                self.rtt_seq = seq_add(self.snd_nxt, size)
                self.rtt_time = time.time()
            self._send_data_at(self.snd_nxt, size)
            self.snd_nxt = seq_add(self.snd_nxt, size)
            if seq_lt(self.snd_max, self.snd_nxt):
                self.snd_max = self.snd_nxt

    def _send_data_at(self, seq, max_size):
        # send (or resend) the data starting at seq; returns the number of bytes sent
        offset = seq_diff(seq, self.send_base)
        size = min(max_size, len(self.send_data) - offset)
        if size <= 0:
            return 0
        flags = tcp.ACK
        if offset + size == len(self.send_data):
            flags |= tcp.PSH
        self._send_segment(flags, seq, self.send_data[offset:offset + size])
        if self.timer is None:
            self.timer = time.time() + self.rto
        return size

    def _on_timeout(self):
        # retransmission timeout: back to slow start from the oldest unacked byte
        flight = seq_diff(self.snd_max, self.snd_una)
        self.ssthresh = max(flight // 2, 2 * self.mss)
        self.cwnd = self.mss
        self.in_recovery = False
        self.dup_acks = 0
        self.rtt_seq = None
        self.rto = min(self.rto * 2, MAX_RTO)
        size = self._send_data_at(self.snd_una, self.mss)
        self.snd_nxt = seq_add(self.snd_una, size)
        self.timer = time.time() + self.rto

    def _handle_ack(self, seg):
        ack = seg["ack"]
        now = time.time()

        if seq_lt(self.snd_una, ack) and seq_le(ack, self.snd_max):
            # new data acknowledged
            acked = seq_diff(ack, self.snd_una)
            self.snd_una = ack
            if seq_lt(self.snd_nxt, ack):
                self.snd_nxt = ack
            self.peer_window = seg["window"]
            self.last_progress = now
            self.dup_acks = 0

            if self.rtt_seq is not None and seq_le(self.rtt_seq, ack):
                self._update_rto(now - self.rtt_time)
                self.rtt_seq = None

            if self.in_recovery:
                if seq_le(self.recover, ack):
                    # everything sent before the loss is acked: recovery is over
                    self.cwnd = self.ssthresh
                    self.in_recovery = False
                else:
                    # partial ACK: the next segment was lost too, resend it right away
                    self._send_data_at(ack, self.mss)
                    self.cwnd = max(self.cwnd - acked + self.mss, self.mss)
            elif self.cwnd < self.ssthresh:
                self.cwnd += min(acked, self.mss)                       # slow start
            else:
                self.cwnd += max(1, self.mss * self.mss // self.cwnd)   # congestion avoidance

            if self.snd_una == self.snd_max:
                self.timer = None
            else:
                self.timer = now + self.rto

        elif ack == self.snd_una:
            is_duplicate = (len(seg["payload"]) == 0
                            and not seg["flags"] & (tcp.SYN | tcp.FIN)
                            and self.snd_una != self.snd_max
                            and seg["window"] == self.peer_window)
            self.peer_window = seg["window"]
            if not is_duplicate:
                return
            self.dup_acks += 1
            if self.dup_acks == 3 and not self.in_recovery:
                # fast retransmit, then fast recovery
                flight = seq_diff(self.snd_max, self.snd_una)
                self.ssthresh = max(flight // 2, 2 * self.mss)
                self.rtt_seq = None
                self._send_data_at(self.snd_una, self.mss)
                self.cwnd = self.ssthresh + 3 * self.mss
                self.in_recovery = True
                self.recover = self.snd_max
            elif self.in_recovery:
                self.cwnd += self.mss

    def _update_rto(self, sample):
        # RFC 6298, clamped to [MIN_RTO, MAX_RTO]
        if self.srtt is None:
            self.srtt = sample
            self.rttvar = sample / 2
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - sample)
            self.srtt = 0.875 * self.srtt + 0.125 * sample
        self.rto = min(MAX_RTO, max(MIN_RTO, self.srtt + 4 * self.rttvar))

    # ---------------- receiving data ----------------

    def recv(self, timeout=-1):
        # returns in-order bytes; b"" once the peer has closed (FIN)
        # timeout <= 0 means wait forever; raises TimeoutError, or ConnectionError on RST
        deadline = None
        if timeout is not None and timeout > 0:
            deadline = time.time() + timeout

        while True:
            if self.recv_buffer:
                data = bytes(self.recv_buffer)
                self.recv_buffer.clear()
                return data
            if self.peer_fin:
                return b""
            if self.state != "ESTABLISHED":
                raise ConnectionError("connection is not open")

            wait = None
            if deadline is not None:
                wait = deadline - time.time()
                if wait <= 0:
                    raise TimeoutError("timed out waiting for data")
            seg = self._next_segment(wait)
            if seg is not None:
                self._handle_segment(seg)

    def _handle_data(self, seg):
        seq = seg["seq"]
        payload = seg["payload"]
        if seg["flags"] & tcp.FIN and self.peer_fin_seq is None:
            self.peer_fin_seq = seq_add(seq, len(payload))

        if payload and not self.peer_fin:
            if seq_le(seq, self.rcv_nxt):
                # in order (possibly overlapping data we already have)
                skip = seq_diff(self.rcv_nxt, seq)
                if skip < len(payload):
                    self.recv_buffer += payload[skip:]
                    self.rcv_nxt = seq_add(self.rcv_nxt, len(payload) - skip)
            elif seq_diff(seq, self.rcv_nxt) < WINDOW:
                # out of order but inside our window: keep it (T12)
                if len(payload) > len(self.out_of_order.get(seq, b"")):
                    self.out_of_order[seq] = payload
            self._deliver_out_of_order()

        if self.peer_fin_seq is not None and not self.peer_fin and self.rcv_nxt == self.peer_fin_seq:
            self.rcv_nxt = seq_add(self.rcv_nxt, 1)     # FIN takes one sequence number
            self.peer_fin = True

        # cumulative ACK for every data segment, even duplicates and out-of-order ones (T11)
        self._send_segment(tcp.ACK, self.snd_nxt)

    def _deliver_out_of_order(self):
        progress = True
        while progress:
            progress = False
            for seq in list(self.out_of_order):
                if seq_le(seq, self.rcv_nxt):
                    payload = self.out_of_order.pop(seq)
                    skip = seq_diff(self.rcv_nxt, seq)
                    if skip < len(payload):
                        self.recv_buffer += payload[skip:]
                        self.rcv_nxt = seq_add(self.rcv_nxt, len(payload) - skip)
                        progress = True

    # ---------------- teardown ----------------

    def close(self):
        if self.state != "ESTABLISHED":
            self.state = "CLOSED"
            self.raw_socket.close()
            return

        self.state = "CLOSING"
        fin_seq = self.snd_nxt
        self.snd_nxt = seq_add(fin_seq, 1)      # FIN takes one sequence number
        self.snd_max = self.snd_nxt
        start = time.time()
        last_sent = None
        try:
            while True:
                now = time.time()
                fin_acked = seq_lt(fin_seq, self.snd_una)
                if fin_acked and self.peer_fin:
                    break
                if now - start >= CLOSE_TIMEOUT:
                    break
                # resend our FIN until it is acked (T9)
                if not fin_acked and (last_sent is None or now - last_sent >= self.rto):
                    self._send_segment(tcp.FIN | tcp.ACK, fin_seq)
                    last_sent = now

                wait = start + CLOSE_TIMEOUT - now
                if not fin_acked:
                    wait = min(wait, last_sent + self.rto - now)
                seg = self._next_segment(wait)
                if seg is not None:
                    self._handle_segment(seg)
        except ConnectionError:
            pass
        finally:
            self.state = "CLOSED"
            self.raw_socket.close()

    # ---------------- packets ----------------

    def _handle_segment(self, seg):
        flags = seg["flags"]
        if flags & tcp.RST:
            self.state = "CLOSED"           # abort immediately (T8)
            raise ConnectionError("connection reset by peer")
        if flags & tcp.SYN:
            # the peer did not get our handshake ACK and resent its SYN-ACK
            self._send_segment(tcp.ACK, self.snd_nxt)
            return
        if flags & tcp.ACK:
            self._handle_ack(seg)
        if seg["payload"] or flags & tcp.FIN:
            self._handle_data(seg)

    def _send_segment(self, flags, seq, payload=b"", mss=None):
        ack = self.rcv_nxt if flags & tcp.ACK else 0
        tcp_hdr = tcp.create_tcp_header(self.local_ip, self.remote_ip, self.local_port, self.remote_port,
                                        seq, ack, flags, WINDOW, payload, mss)
        ident = self.ip_id
        self.ip_id = self.ip_id % 65535 + 1         # 1..65535, never 0 (T1)
        ip_hdr = ip_header.create_ip_header(self.local_ip, self.remote_ip, len(tcp_hdr) + len(payload), ident, TTL)
        try:
            self.raw_socket.sendto(ip_hdr + tcp_hdr + payload, (self.remote_ip, 0))
        except OSError:
            return          # treated like a lost packet; retransmission takes care of it
        sent = {"source_port": self.local_port, "dest_port": self.remote_port, "seq": seq, "ack": ack,
                "flags": flags, "window": WINDOW, "mss": mss, "payload": payload}
        self._log("SEND", self.local_ip, self.remote_ip, TTL, ident, sent)

    def _receive_packet(self, wait):
        # one TCP packet with valid checksums as (ip, seg) dicts, or None on timeout / bad packet
        if wait is None:
            self.raw_socket.settimeout(None)
        else:
            self.raw_socket.settimeout(max(wait, 0.001))
        try:
            packet, _ = self.raw_socket.recvfrom(65535)
        except socket.timeout:
            return None
        try:
            ip = ip_header.parse_ip_header(packet)
            if ip["protocol"] != socket.IPPROTO_TCP:
                return None
            seg = tcp.parse_tcp_header(ip["source_ip"], ip["dest_ip"], ip["payload"])
        except ValueError:
            return None     # bad checksum or malformed: drop silently (T4)
        return ip, seg

    def _next_segment(self, wait):
        # like _receive_packet, but only segments of this connection (T5), which get logged
        packet = self._receive_packet(wait)
        if packet is None:
            return None
        ip, seg = packet
        if (ip["source_ip"] != self.remote_ip or ip["dest_ip"] != self.local_ip
                or seg["source_port"] != self.remote_port or seg["dest_port"] != self.local_port):
            return None
        self._log("RECV", ip["source_ip"], ip["dest_ip"], ip["ttl"], ip["identification"], seg)
        return seg

    def _log(self, direction, src_ip, dst_ip, ttl, ident, seg):
        if self.log is None:
            return
        mss = seg["mss"] if seg["mss"] is not None else "-"
        self.log.write(f"{direction} {src_ip}:{seg['source_port']} > {dst_ip}:{seg['dest_port']} "
                       f"ttl={ttl} id={ident} seq={seg['seq']} ack={seg['ack']} flags=0x{seg['flags']:02x} "
                       f"win={seg['window']} len={len(seg['payload'])} mss={mss}\n")
        self.log.flush()
