"""First-prompt size (system prompt + tool schemas) of a core checkout, fresh install, Tempest defaults.

    python bench/tempest_v2_prompt.py /path/to/core

Prints chars and a chars/4 token estimate for the system prompt and for the tools array as sent.
Run it on two checkouts to compare (numbers are estimates; the live bench reports provider tokens).
"""

import json
import os
import sys
import tempfile
from pathlib import Path

core = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(core))
os.environ["NEOVARCH_HOME"] = tempfile.mkdtemp(prefix="nvp-")
os.environ.update({"NEOVARCH_9ROUTER_SUPERVISE": "0", "NEOVARCH_9ROUTER_AUTOSTART": "0"})

from neovarch.paths import ensure_home  # noqa: E402

ensure_home()
from neovarch import config as cfgmod, tempest, tempest_diet  # noqa: E402
from neovarch.agent import Agent, system_prompt  # noqa: E402
from neovarch.store import SessionStore  # noqa: E402
from neovarch.tools import ToolContext  # noqa: E402

cfg = cfgmod.load_config()
st = tempest.settings(cfg)
cwd = Path(tempfile.mkdtemp())
sysp = system_prompt(cfg, cwd, "", "", stable=True, diet=tempest_diet.enabled(st))
store = SessionStore()
agent = Agent(store.create(cwd=str(cwd)), store, ToolContext(cwd=cwd, approve=None), lambda k, p: None)
agent._tempest = st
tools = agent._tools()
tj = json.dumps(tools, ensure_ascii=False)
print(json.dumps({"core": str(core), "system_chars": len(sysp), "system_tokens_est": (len(sysp) + 3) // 4,
                  "tools": len(tools), "tools_chars": len(tj), "tools_tokens_est": (len(tj) + 3) // 4,
                  "total_tokens_est": (len(sysp) + len(tj) + 6) // 4,
                  "tool_names": [t["function"]["name"] for t in tools]}))
