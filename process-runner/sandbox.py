"""Entrypoint inside the disposable sandbox. Its output is untrusted."""

import json
import sys
from typing import Any
from uuid import uuid4


def main() -> None:
    transport = sys.stdout
    sys.stdout = sys.stderr
    request = json.loads(sys.stdin.readline())
    handles = request["handles"]

    def send(frame: dict[str, Any]) -> None:
        transport.write(json.dumps(frame, ensure_ascii=False, allow_nan=False) + "\n")
        transport.flush()

    def call_service(name: str, arguments: dict[str, Any]) -> Any:
        call_id = str(uuid4())
        send({"call": {"id": call_id, "handle": handles[name], "arguments": arguments}})
        reply = json.loads(sys.stdin.readline())
        if reply["status"] != "completed":
            raise RuntimeError("Service rejected the capability call")
        return reply["output"]

    values = {**request["values"], "call_service": call_service}
    exec(compile(request["source"], "<process-python>", "exec", dont_inherit=True), values)
    send({"result": {name: values[name] for name in ("output", "output_files") if name in values}})


if __name__ == "__main__":
    main()
