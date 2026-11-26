#!/usr/bin/python3 -I
"""Start the bundled Claude CLI with an explicit, run-local environment."""

import os
import sys


def main() -> None:
    binary = os.environ["GALARIS_CLAUDE_BINARY"]
    workspace = os.environ["GALARIS_CLAUDE_WORKSPACE"]
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": workspace,
        "CLAUDE_CONFIG_DIR": workspace,
        "TMPDIR": workspace,
        "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
        "CLAUDE_AGENT_SDK_VERSION": os.environ["CLAUDE_AGENT_SDK_VERSION"],
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "ENABLE_TOOL_SEARCH": "false",
        "ANTHROPIC_BASE_URL": os.environ["GALARIS_CLAUDE_GATEWAY"],
        "ANTHROPIC_API_KEY": os.environ["GALARIS_CLAUDE_CREDENTIAL"],
    }
    os.execve(binary, [binary, *sys.argv[1:]], environment)


if __name__ == "__main__":
    main()
