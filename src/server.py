import argparse
import custom_http
import sys, os


class handler: 
    def __init__(self, document_root: str, logfile: str):
        self.document_root=document_root
        self.logfile=logfile
        # check if document_root is valid directory
        if not os.path.isdir(document_root):
            print(f"Error: {document_root} is not a valid directory")
            sys.exit(1)


    def execute_get(self, request: custom_http.HTTPRequest, time_budget: float) -> custom_http.HTTPResponse:
        # figuring out the file path
        host, port, path, q=custom_http.process_url(request.url)
        file_path = self.document_root + path

        if os.path.isdir(file_path):
            file_path = os.path.join(file_path, "index.html")

        idx=len(file_path)-1
        extension=""
        while idx>0 and (file_path[idx]!='/' and file_path[idx]!='.'):
            extension=file_path[idx]+extension
            idx-=1
            if(file_path[idx]=='.'):
                extension=file_path[idx]+extension
                break
            elif (file_path[idx]=='/'):
                extension=""
                break
        # figure out content type 
        content_type= ""
        match extension.lower():
            case ".html" | ".htm":
                content_type="text/html"
            case ".txt":
                content_type="text/plain"
            case ".css":
                content_type="text/css"
            case ".js":
                content_type="application/javascript"
            case ".json":
                content_type="application/json"
            case ".png":
                content_type="image/png"
            case ".jpg" | ".jpeg":
                content_type="image/jpeg"
            case ".gif":
                content_type="image/gif"
            case ".pdf":
                content_type="application/pdf"
            case _:
                content_type="application/octet-stream"

        # check for the 400, is already done in the custom_http where we parse the response.

        if request.method!="GET" and request.method!="HEAD":
            res=custom_http.HTTPResponse()
            res.reason=b"Not Implemented"
            res.status_code=501
            res.content=b"<p>501 Not Implemented</p>"
            res.headers={
                "Content-Type": "text/html",
                "Content-Length": str(len(res.content)),
                "Connection": "close"
            }
            return res

        if path.__contains__("../") or path.__contains__("/.."):
            res=custom_http.HTTPResponse()
            res.reason=b"Forbidden"
            res.status_code=403
            res.content=b"<p>403 Forbidden</p>"
            res.headers={
                "Content-Type": "text/html",
                "Content-Length": str(len(res.content)),
                "Connection": "close" 
            }
            return res

        if not os.path.isfile(file_path):
            res=custom_http.HTTPResponse()
            res.reason=b"Not Found"
            res.status_code=404
            res.content=b"<p>404 Not Found</p>"
            res.headers={
                "Content-Type": "text/html",
                "Content-Length": str(len(res.content)),
                "Connection": "close"
            }
            return res
            

        # now read the file and create the content for the response
        with open(file_path, "rb") as f:
            content=f.read()

        res=custom_http.HTTPResponse()
        res.status_code=200
        res.content=content
        res.headers={
            "Content-Type": content_type,
            "Content-Length": str(len(res.content)),
            "Connection": "close"
        }
        res.content=res.content if request.method=="GET" else b""
        return res
        
        

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("-p", "--port",
                        type=int, default=8080)
    parser.add_argument("-d", "--document_root", type=str, default="./www")
    parser.add_argument("-l", "--logfile", type=str, default="./server.log")
    args=parser.parse_args()
    docroot=args.document_root
    logfile=args.logfile
    port=args.port
    server=custom_http.CustomHTTP.Server(handler(docroot, logfile), port)
    server.serve_forever()
