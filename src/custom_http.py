
from dataclasses import dataclass
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
    host, port, rest = "", 8080, url
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
    idx = data.find("\r\n\r\n")
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
        def __init__(self):
            self.socket=custom_socket.CustomTCPSocket()
            pass

        def send_request(self, request: HTTPRequest)-> HTTPResponse: 
            reciever_ip, reciever_port, _, _ = process_url(request.url)
            self.socket.connect(reciever_ip, reciever_port)
            req=self.convert_request_to_bytes(request)
            while True: 
                sent_bytes=self.socket.send(req)
                req=req[sent_bytes:]
                if len(req)==0:
                    break
            # request sent, now the response
            res=""
            while True: 
                response=self.socket.recv().decode('utf-8')
                if response=='':
                    break
                res+=response
            
            res=self.parse_response(res)
            if(len(res.content)!=int(res.headers.get("Content-Length", 0))):
                raise Exception("Content-Length mismatch")
            return res

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
        def __init__(self, handler, port):
            # I am expecting handler to have
            # method execute_get(request: HTTPRequest, time_budget: float)
            # and returns HTTPResponse
            # No need the host, as we need to listen to all incoming connections at the port

            self.handler=handler
            self.port=port
            self.socket=custom_socket.CustomTCPSocket()

        def serve_forever(self):
            while True:
                ip, port=self.socket.accept(self.port)
                #get the complete request from client
                start=time.time()
                req=""
                while True: 
                    request=self.socket.recv().decode('utf-8')
                    if request=='':
                        continue
                    if time.time()-start>10:
                        break
                    req+=request
                    if '\r\n\r\n' in req:
                        break
                if time.time()-start>10:
                    self.socket.close()
                    continue
                parsed = self.parse_request(req)
                if isinstance(parsed, HTTPResponse):        # malformed -> 400, handler never runs
                    response = parsed
                else:
                    response = self.handler.execute_get(parsed, 10 - (time.time() - start))
                res=self.convert_response_to_bytes(response)
                while True: 
                    sent_bytes=self.socket.send(res, 10-(time.time()-start))
                    res=res[sent_bytes:]
                    if len(res)==0:
                        break
                    if time.time()-start>10:
                        break
                self.socket.close()

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



