import socket
import struct

from ip_header import checksum, ip_to_bytes, check_range, IP_HEADER_LEN

# source port, dest port, seq, ack, data offset, flags, window, checksum, urgent pointer
TCP_HEADER_FORMAT = "!HHLLBBHHH"
TCP_HEADER_LEN = 20
# source IP, dest IP, zero, protocol, TCP length
PSEUDO_HEADER_FORMAT = "!4s4sBBH"

FIN = 0x01
SYN = 0x02
RST = 0x04
PSH = 0x08
ACK = 0x10

MSS_OPTION_KIND = 2
MSS_OPTION_LEN = 4


def create_tcp_header(source_ip, dest_ip, source_port, dest_port, seq, ack, flags, window=65535, payload=b"", mss=None):
    # source_ip and dest_ip are only used for the pseudo-header in the checksum
    src = ip_to_bytes(source_ip)
    dst = ip_to_bytes(dest_ip)
    check_range("source_port", source_port, 1, 65535)
    check_range("dest_port", dest_port, 1, 65535)
    check_range("seq", seq, 0, 2**32 - 1)
    check_range("ack", ack, 0, 2**32 - 1)
    check_range("flags", flags, 0, 255)
    check_range("window", window, 0, 65535)
    if type(payload) != bytes:
        raise TypeError(f"payload must be bytes, got {type(payload).__name__}")

    # only option we ever send is MSS, on SYN and SYN-ACK (T3)
    options = b""
    if mss is not None:
        check_range("mss", mss, 1, 65535)
        options = struct.pack("!BBH", MSS_OPTION_KIND, MSS_OPTION_LEN, mss)

    header_len = TCP_HEADER_LEN + len(options)
    tcp_length = header_len + len(payload)
    if tcp_length > 65535 - IP_HEADER_LEN:
        raise ValueError(f"segment too large: {tcp_length} bytes")

    data_offset = (header_len // 4) << 4

    # checksum covers the pseudo-header, the TCP header (checksum field 0) and the payload
    pseudo_header = struct.pack(PSEUDO_HEADER_FORMAT, src, dst, 0, socket.IPPROTO_TCP, tcp_length)
    header = struct.pack(TCP_HEADER_FORMAT, source_port, dest_port, seq, ack,
                         data_offset, flags, window, 0, 0) + options
    tcp_checksum = checksum(pseudo_header + header + payload)
    return struct.pack(TCP_HEADER_FORMAT, source_port, dest_port, seq, ack,
                       data_offset, flags, window, tcp_checksum, 0) + options


def parse_tcp_header(source_ip, dest_ip, segment):
    # source_ip and dest_ip come from the IP header, needed for the pseudo-header checksum
    # returns a dict of the header fields plus the payload; raises ValueError for a bad segment
    src = ip_to_bytes(source_ip)
    dst = ip_to_bytes(dest_ip)
    if type(segment) != bytes:
        raise TypeError(f"segment must be bytes, got {type(segment).__name__}")
    if len(segment) < TCP_HEADER_LEN:
        raise ValueError(f"segment too short: {len(segment)} bytes")
    if len(segment) > 65535:
        raise ValueError(f"segment too large: {len(segment)} bytes")

    (source_port, dest_port, seq, ack, data_offset, flags,
     window, tcp_checksum, urgent) = struct.unpack(TCP_HEADER_FORMAT, segment[:TCP_HEADER_LEN])

    header_len = (data_offset >> 4) * 4
    if header_len < TCP_HEADER_LEN or header_len > len(segment):
        raise ValueError(f"bad TCP header length: {header_len}")

    # checksum over pseudo-header + whole segment is 0 when it is correct (T4)
    pseudo_header = struct.pack(PSEUDO_HEADER_FORMAT, src, dst, 0, socket.IPPROTO_TCP, len(segment))
    if checksum(pseudo_header + segment) != 0:
        raise ValueError("bad TCP checksum")

    # options: keep the peer's MSS, ignore everything else (T4)
    mss = None
    options = segment[TCP_HEADER_LEN:header_len]
    i = 0
    while i < len(options):
        kind = options[i]
        if kind == 0:               # end of options
            break
        if kind == 1:               # no-op, single byte
            i += 1
            continue
        if i + 1 >= len(options):
            raise ValueError("truncated TCP option")
        length = options[i + 1]
        if length < 2 or i + length > len(options):
            raise ValueError(f"bad TCP option length: {length}")
        if kind == MSS_OPTION_KIND and length == MSS_OPTION_LEN:
            mss = struct.unpack("!H", options[i + 2:i + 4])[0]
        i += length

    return {
        "source_port": source_port,
        "dest_port": dest_port,
        "seq": seq,
        "ack": ack,
        "header_len": header_len,
        "flags": flags,
        "window": window,
        "checksum": tcp_checksum,
        "urgent": urgent,
        "mss": mss,
        "payload": segment[header_len:],
    }
