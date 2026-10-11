import custom_http
import argparse, sys

if "__main__" == __name__:
    parser=argparse.ArgumentParser()
    parser.add_argument("url", type=str)
    parser.add_argument("-o", "--outfile", type=str, default="")
    parser.add_argument("-l", "--log", type=str, default="./client.log")

    args=parser.parse_args()
    outfile=args.outfile
    logfile=args.log
    url=args.url

    conn=custom_http.CustomHTTP.ClientConnection()

    request=custom_http.HTTPRequest()
    request.method="GET"
    request.url=url
    request.body=b""
    host, port, _, _=custom_http.process_url(url)

    request.headers={
        "Connection": "close", 
        "Host": host+":" + str(port) if port!=-1 else host,
    }
    try:
        response= conn.send_request(request)
        if outfile!="":
            with open(outfile, "wb") as f:
                f.write(response.content)
        else:
            sys.stdout.buffer.write(response.content)
        print(f"HTTP/1.1 {response.status_code} {response.reason.decode('utf-8')}", file=sys.stderr)
        if response.status_code<200 or response.status_code>=300:
            exit(1)
        else:
            exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        exit(2)
   
