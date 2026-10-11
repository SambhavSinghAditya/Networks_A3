import custom_http
import argparse, sys

if "__main__" == __name__:
    parser=argparse.ArgumentParser()
    parser.add_argument("url", type=str)
    parser.add_argument("-o", "--outfile", type=str, default="")
    parser.add_argument("-l", "--log", type=str, default=None)

    args=parser.parse_args()
    outfile=args.outfile
    logfile=args.log
    url=args.url

    try:
        host, port, _, _=custom_http.process_url(url)
        conn=custom_http.CustomHTTP.ClientConnection(logfile)

        request=custom_http.HTTPRequest()
        request.method="GET"
        request.url=url
        request.body=b""
        request.headers={
            "Connection": "close", 
            "Host": host+":" + str(port) if port!=-1 else host,
        }
        response= conn.send_request(request)
        if outfile!="":
            with open(outfile, "wb") as f:
                f.write(response.content)
        else:
            sys.stdout.buffer.write(response.content)
            sys.stdout.buffer.flush()
        print(f"HTTP/1.1 {response.status_code} {response.reason.decode('latin-1')}", file=sys.stderr)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if 200<=response.status_code<300 else 1)
