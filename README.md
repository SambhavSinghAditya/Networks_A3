# COL334 Assignment 3 — TCP and HTTP over Raw Sockets

## Team
- Sambhav Singh Aditya — 2024CS10177
- Utkarsh Agrawal — 2024CS10076

## What this assignment does
We build a small four-machine network by hand and run our own HTTP client and server on it, over our own TCP.

| Part | What | Where |
|------|------|-------|
| A | Static IP/route config for 4 VMs (client, r1, r2, server) | `netcfg/*.sh` |
| B | TCP/IPv4 on raw sockets: handshake, retransmission, out-of-order buffering, Reno-style congestion control, packet log | `src/custom_socket.py`, `src/tcp.py`, `src/ip_header.py` |
| C | HTTP/1.1 GET client (Content-Length, chunked, close-delimited bodies) | `src/client.py`, `src/custom_http.py` |
| D | HTTP server serving files from a directory (GET/HEAD, 400/403/404/501) | `src/server.py`, `src/custom_http.py` |
| E | Our client downloads from our server across the VM network | — |

Topology: `client — LAN A — r1 — LAN B — r2 — LAN C — server`, plus a direct `client — Link D — r2` link.
Client→server goes via r1 and r2; server→client returns via r2 and Link D.

## Requirements
- Four Ubuntu VMs (22.04 preferred) on isolated internal networks (LAN A, B, C, Link D).
- Python 3.10+ (standard library only; the code uses `match`, so 3.10 is the minimum).
- Root access (raw sockets, `ip`, `sysctl`, `iptables`).
- No build step. There is no Makefile.

## Setup
1. Create the 4 VMs and attach each only to its internal networks:
   - client: LAN A, Link D
   - r1: LAN A, LAN B
   - r2: LAN B, LAN C, Link D
   - server: LAN C
2. On every interface of every VM, set `rp_filter` to 1 (Ubuntu defaults to 2):
   ```sh
   sudo sysctl -w net.ipv4.conf.all.rp_filter=1
   sudo sysctl -w net.ipv4.conf.<IF>.rp_filter=1   # for each interface
   ```
3. Copy this repo onto each VM.
4. Run the config script on each VM as root, with that VM's interface names (`ip -br link` lists them):
   ```sh
   sudo ./netcfg/client.sh IF_A IF_D
   sudo ./netcfg/r1.sh     IF_A IF_B
   sudo ./netcfg/r2.sh     IF_B IF_C IF_D
   sudo ./netcfg/server.sh IF_C
   ```
   Each script runs once on a freshly booted machine.
5. On every VM (client, r1, r2, server), as root, drop the kernel's own RSTs. The launchers add this rule only on the VM they run on, so add it by hand everywhere before testing with `curl`, `wget` or `python3 -m http.server`:
   ```sh
   sudo iptables -C OUTPUT -p tcp --tcp-flags RST RST -j DROP 2>/dev/null || \
       sudo iptables -A OUTPUT -p tcp --tcp-flags RST RST -j DROP
   ```
   (`-C` checks first, so running it twice does not add a duplicate. The rule is lost on reboot.)
6. Check connectivity, for example `ping 10.10.3.10` from the client and `traceroute -n 10.10.3.10`.

## Running
Both launchers add the iptables rule from Setup step 5 if it is missing (the kernel doesn't know about our raw-socket TCP and would reset our connections), then start the Python program. Run them as root.

**Server** (on the server VM):
```sh
sudo ./server/run-server [-p PORT] [-d DOCROOT] [--log LOGFILE]
# defaults: -p 8080 -d ./www
```

**Client** (on the client VM):
```sh
sudo ./client/run-client http://HOST[:PORT][/PATH] [-o OUTFILE] [--log LOGFILE]
```
Without `-o` the body goes to stdout. The status line is printed to stderr.

Exit codes: `0` for a 2xx response, `1` for any other complete response, `2` for an error (bad URL, refused, timeout, incomplete body).

### Example
```sh
# server VM
mkdir -p www && echo "<h1>hello</h1>" > www/index.html
sudo ./server/run-server -p 8080 -d ./www --log server.log

# client VM
sudo ./client/run-client http://10.10.3.10:8080/ -o out.html --log client.log
md5sum out.html www/index.html   # must match
curl -s http://10.10.3.10:8080/ | md5sum   # compare against the standard client
```

### Testing with curl, wget and a standard server
Do Setup step 5 on every VM first. Then, with our server running on the server VM, from the client VM:
```sh
curl -v  http://10.10.3.10:8080/                    # body + headers
curl -sI http://10.10.3.10:8080/                    # HEAD request
curl -s  -o out.html http://10.10.3.10:8080/index.html
wget -O out.html http://10.10.3.10:8080/index.html
curl -s -o /dev/null -w "%{http_code}\n" http://10.10.3.10:8080/missing   # expect 404
```
With a standard server on the server VM, run our client against it:
```sh
# server VM
python3 -m http.server 8000 --bind 0.0.0.0
# client VM
sudo ./client/run-client http://10.10.3.10:8000/ -o out.html --log client.log
```

## Packet log
With `--log FILE`, each sent or accepted TCP segment is written as one line:
```
SEND 10.10.1.10:62425 > 10.10.3.10:8000 ttl=64 id=301 seq=1000 ack=0 flags=0x02 win=65535 len=0 mss=1460
```

## Notes
- Client and server must run on different machines (no loopback).
- Only raw IP sockets with `IP_HDRINCL` are used for TCP traffic. No kernel TCP and no HTTP libraries.
- Scripts under `netcfg/` use only `ip` and `sysctl`.
