"""Local synthetic, READ-ONLY JSON-RPC fixture for plan-only UI demonstrations.

Run separately on 127.0.0.1:8547. Never accepts signing or submission methods.
"""

import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer


def answer(method, params):
    if method == "eth_chainId":
        return hex(11155111)
    if method == "eth_getBlockByNumber":
        return {
            "number": hex(123456),
            "timestamp": hex(int(datetime.now(UTC).timestamp())),
            "hash": "0x" + "ab" * 32,
            "baseFeePerGas": hex(10**9),
        }
    if method == "eth_getBalance":
        return hex(50000000000000000)  # Synthetic 0.05 ETH, never a real balance.
    if method == "eth_getTransactionCount":
        return "0x0"
    if method == "eth_getCode":
        return "0x"
    if method == "eth_estimateGas":
        return hex(21000)
    if method == "eth_maxPriorityFeePerGas":
        return hex(10**9)
    raise ValueError("Read-only fixture: unsupported method")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 8192:
                raise ValueError("Invalid body size")
            data = json.loads(self.rfile.read(size))
            response = {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "result": answer(data["method"], data.get("params", [])),
            }
        except Exception:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32601, "message": "Read-only synthetic fixture"},
            }
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Synthetic read-only Treasury RPC on 127.0.0.1:8547. No signing or broadcasting.")
    HTTPServer(("127.0.0.1", 8547), Handler).serve_forever()
