
from dataclasses import dataclass
import socket
import time
import custom_socket
@dataclass
class HTTPRequest:
    method: str = "GET"
    url: str = ""
    headers: dict = None
    body: bytes = b""

@dataclass
class HTTPResponse:
    status_code: int = 200
    headers: dict = None
    content: bytes = b""
    reason: bytes = b"OK"


def process_url(url: str) -> tuple[str, int, str, str]:

    url = url.split("#", 1)[0]
    host, port, rest = "", -1, url
    if not url.startswith("/"):
        if url[:7].lower() != "http://":
            raise ValueError("URL must start with http://")
        rest = url[7:]
        cut = len(rest)
        for ch in "/?":
            i = rest.find(ch)
            if i != -1:
                cut = min(cut, i)
        authority, rest = rest[:cut], rest[cut:]
        host = authority
        if ":" in authority:
            host, p = authority.rsplit(":", 1)
            if not p.isdigit() or not 0 < int(p) < 65536:
                raise ValueError("bad port")
            port = int(p)
        if host == "":
            raise ValueError("empty host")
    path, _, query = rest.partition("?")
    if path == "":
        path = "/"
    return host, port, path, query


def _split_head(data: bytes):
    """bytes -> (first_line, headers{lowercase name: value}, rest_after_head)"""
    idx = data.find(b"\r\n\r\n")
    if idx == -1:
        raise ValueError("incomplete HTTP head")
    lines = data[:idx].split(b"\r\n")
    headers = {}
    for line in lines[1:]:
        name, sep, value = line.partition(b":")
        if sep:
            headers[name.strip().lower().decode("latin-1")] = value.strip().decode("latin-1")
    return lines[0], headers, data[idx + 4:]


def _decode_chunked(data: bytes) -> bytes:
    out, pos = b"", 0
    while True:
        eol = data.find(b"\r\n", pos)
        if eol == -1:
            raise ValueError("incomplete chunk header")
        size = int(data[pos:eol].split(b";", 1)[0].strip(), 16)  # ignore chunk extensions
        pos = eol + 2
        if size == 0:
            if b"\r\n\r\n" not in data[pos - 2:]:   # trailers ignored, but must be terminated
                raise ValueError("incomplete chunked body")
            return out
        if len(data) < pos + size + 2:
            raise ValueError("incomplete chunk")
        out += data[pos:pos + size]
        pos += size + 2


class CustomHTTP: 
    class ClientConnection: 
        def __init__(self, logfile=None):
            self.socket=custom_socket.CustomTCPSocket(logfile)

        @staticmethod
        def _complete(data: bytes) -> bool:
            """True once Content-Length / chunked framing says the response is whole."""
            try:
                _, headers, body = _split_head(data)
                status = int(data.split(b" ", 2)[1])
            except (ValueError, IndexError):
                return False
            if status in (204, 304) or 100 <= status < 200:
                return True
            if "chunked" in headers.get("transfer-encoding", "").lower():
                try:
                    _decode_chunked(body)
                    return True
                except ValueError:
                    return False
            if "content-length" in headers:
                try:
                    return len(body) >= int(headers["content-length"])
                except ValueError:
                    return False
            return False        # read-until-close

        def send_request(self, request: HTTPRequest)-> HTTPResponse: 
            reciever_ip, reciever_port, _, _ = process_url(request.url)
            reciever_ip = socket.gethostbyname(reciever_ip)     # name -> IP (raises on failure)
            try:
                self.socket.connect(reciever_ip, reciever_port if reciever_port != -1 else 80)
                req=self.convert_request_to_bytes(request)
                while req:
                    req=req[self.socket.send(req):]
                # request sent, now the response
                res=b""
                while not self._complete(res):
                    chunk=self.socket.recv(10)      # TimeoutError / ConnectionError -> exit 2
                    if chunk==b"":                  # peer FIN
                        break
                    res+=chunk
                return self.parse_response(res)
            finally:
                self.socket.close()

        def convert_request_to_bytes(self, request: HTTPRequest) -> bytes:
            _, _, path, query = process_url(request.url)
            target = path + ("?" + query if query else "")      # PATH verbatim, query kept
            head = f"{request.method} {target} HTTP/1.1\r\n"
            for k, v in (request.headers or {}).items():
                head += f"{k}: {v}\r\n"
            return head.encode("utf-8") + b"\r\n" + (request.body or b"")

        def parse_response(self, response: bytes) -> HTTPResponse:
            status_line, headers, body = _split_head(response)
            parts = status_line.split(b" ", 2)
            if len(parts) < 2 or not parts[0].startswith(b"HTTP/") or not parts[1].isdigit():
                raise ValueError("bad status line")
            status = int(parts[1])
            reason = parts[2] if len(parts) == 3 else b""

            if status in (204, 304) or 100 <= status < 200:
                body = b""
            elif "chunked" in headers.get("transfer-encoding", "").lower():
                body = _decode_chunked(body)
            elif "content-length" in headers:
                n = int(headers["content-length"])
                if n < 0 or len(body) < n:
                    raise ValueError("incomplete body")          # -> client exit 2
                body = body[:n]
            # else: read-until-close, whole rest is the body
            return HTTPResponse(status_code=status, headers=headers, content=body, reason=reason)

        

    class Server: 
        def __init__(self, handler, port, logfile=None):
            # I am expecting handler to have
            # method execute_get(request: HTTPRequest, time_budget: float)
            # and returns HTTPResponse
            # No need the host, as we need to listen to all incoming connections at the port

            self.handler=handler
            self.port=port
            self.logfile=logfile

        def serve_forever(self):
            while True:
                sock=custom_socket.CustomTCPSocket(self.logfile)   # fresh state per connection
                try:
                    sock.accept(self.port)
                    # 10s covers reading the request head only
                    start=time.time()
                    req=b""
                    while b"\r\n\r\n" not in req and len(req)<65536:
                        left=10-(time.time()-start)
                        if left<=0:
                            raise TimeoutError("request head timeout")
                        chunk=sock.recv(left)
                        if chunk==b"":              # client closed early: no response
                            raise ConnectionError("closed before request head")
                        req+=chunk
                    parsed = self.parse_request(req)
                    if isinstance(parsed, HTTPResponse):        # malformed -> 400, handler never runs
                        response = parsed
                    else:
                        response = self.handler.execute_get(parsed, 10 - (time.time() - start))
                    res=self.convert_response_to_bytes(response)
                    while res:
                        res=res[sock.send(res):]
                except Exception:
                    pass                            # never die on a bad client
                finally:
                    try:
                        sock.close()
                    except Exception:
                        pass

        def parse_request(self, request: bytes) -> HTTPRequest | HTTPResponse:
            try:
                line, headers, _ = _split_head(request)
                parts = line.split(b" ")
                if len(parts) != 3 or not parts[2].startswith(b"HTTP/"):
                    raise ValueError("bad request line")
                method = parts[0].decode("latin-1")
                target = parts[1].decode("latin-1")
                if method == "" or not target.startswith("/"):
                    raise ValueError("bad target")
                return HTTPRequest(method=method, url=target, headers=headers, body=b"")
            except ValueError:
                body = b"<h1>400 Bad Request</h1>"
                return HTTPResponse(
                    status_code=400,
                    headers={"Content-Type": "text/html", "Content-Length": str(len(body)), "Connection": "close"},
                    content=body,
                    reason=b"Bad Request",
                )


        def convert_response_to_bytes(self, response: HTTPResponse) -> bytes:
            headers = dict(response.headers or {})
            have = {k.lower() for k in headers}
            if "content-length" not in have:
                headers["Content-Length"] = str(len(response.content))
            if "connection" not in have:
                headers["Connection"] = "close"
            head = b"HTTP/1.1 %d %s\r\n" % (response.status_code, response.reason)
            for k, v in headers.items():
                head += f"{k}: {v}\r\n".encode("latin-1")
            return head + b"\r\n" + response.content



