import socket
import struct

# version+IHL, TOS, total length, id, flags+fragment offset, TTL, protocol, checksum, src, dst
IP_HEADER_FORMAT = "!BBHHHBBH4s4s"
IP_HEADER_LEN = 20
DONT_FRAGMENT = 0x4000


def checksum(data):
    # Internet checksum, also used for TCP
    if len(data) % 2 == 1:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) + data[i + 1]
    while total > 0xFFFF:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def ip_to_bytes(ip):
    # "10.10.1.10" -> b"\x0a\x0a\x01\x0a"
    if type(ip) == bytes:
        if len(ip) != 4:
            raise ValueError(f"IP address must be 4 bytes, got {len(ip)}")
        return ip
    if type(ip) != str:
        raise TypeError(f"IP address must be str or bytes, got {type(ip).__name__}")
    try:
        return socket.inet_pton(socket.AF_INET, ip)
    except OSError:
        raise ValueError(f"invalid IP address: {ip}")


def check_range(name, value, low, high):
    if type(value) != int:
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < low or value > high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value}")


def create_ip_header(source_ip, dest_ip, payload_length, identification, ttl=64, protocol=socket.IPPROTO_TCP, tos=0):
    src = ip_to_bytes(source_ip)
    dst = ip_to_bytes(dest_ip)
    check_range("payload_length", payload_length, 0, 65535 - IP_HEADER_LEN)
    check_range("identification", identification, 1, 65535)   # must be non-zero (T1)
    check_range("ttl", ttl, 1, 255)
    check_range("protocol", protocol, 0, 255)
    check_range("tos", tos, 0, 255)

    version_ihl = (4 << 4) | (IP_HEADER_LEN // 4)
    total_length = IP_HEADER_LEN + payload_length

    # checksum is computed over the header with the checksum field set to 0
    header = struct.pack(IP_HEADER_FORMAT, version_ihl, tos, total_length, identification,
                         DONT_FRAGMENT, ttl, protocol, 0, src, dst)
    header_checksum = checksum(header)
    return struct.pack(IP_HEADER_FORMAT, version_ihl, tos, total_length, identification,
                       DONT_FRAGMENT, ttl, protocol, header_checksum, src, dst)


def parse_ip_header(packet):
    # returns a dict of the header fields plus the payload; raises ValueError for a bad packet
    if type(packet) != bytes:
        raise TypeError(f"packet must be bytes, got {type(packet).__name__}")
    if len(packet) < IP_HEADER_LEN:
        raise ValueError(f"packet too short: {len(packet)} bytes")

    (version_ihl, tos, total_length, identification, flags_fragment,
     ttl, protocol, header_checksum, src, dst) = struct.unpack(IP_HEADER_FORMAT, packet[:IP_HEADER_LEN])

    version = version_ihl >> 4
    header_len = (version_ihl & 0x0F) * 4
    if version != 4:
        raise ValueError(f"not IPv4: version {version}")
    if header_len < IP_HEADER_LEN or header_len > len(packet):
        raise ValueError(f"bad header length: {header_len}")
    if total_length < header_len or total_length > len(packet):
        raise ValueError(f"bad total length: {total_length}")
    # checksum over the whole header (options included) is 0 when it is correct
    if checksum(packet[:header_len]) != 0:
        raise ValueError("bad IP checksum")
    # fragments are not supported: drop anything with More Fragments set or a non-zero offset
    if flags_fragment & 0x2000 or flags_fragment & 0x1FFF:
        raise ValueError("fragmented packet")

    return {
        "header_len": header_len,
        "tos": tos,
        "total_length": total_length,
        "identification": identification,
        "ttl": ttl,
        "protocol": protocol,
        "checksum": header_checksum,
        "source_ip": socket.inet_ntoa(src),
        "dest_ip": socket.inet_ntoa(dst),
        "payload": packet[header_len:total_length],   # anything past total_length is padding
    }
