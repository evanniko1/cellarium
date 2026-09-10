# Connecting your own agent (MCP)

Cellarium can be driven by **your** agent, not only by its own CLI and web app. It speaks
[MCP](https://modelcontextprotocol.io) over stdio: your client spawns `python -m cellarium.mcp` as a local
subprocess and talks to it on stdin/stdout.

Nothing is hosted. There is no network service, no account, no shared server. The API key used is yours,
already in your OS keychain (see [Credentials](CREDENTIALS.md)), and it never enters any model's context.

---

## Setting it up

```bash
pip install "cellarium[mcp]"
```

Then add Cellarium to your client's MCP configuration:

```json
{
  "mcpServers": {
    "cellarium": {
      "command": "python",
      "args": ["-m", "cellarium.mcp"]
    }
  }
}
```

That is the whole setup. `cellarium-mcp` is installed as a console script too, if your client prefers to
name a command rather than an interpreter and a module.

---

## What your agent sees: three tools, not seventy-two

| Tool | What it does |
|---|---|
| `ask_cellwright(question)` | Runs the full grounded investigation loop and returns an answer with every number traced to a tool result — plus the run ids behind it, so you can check. |
| `convene_council(question)` | Turns an open question into a falsifiable hypothesis. Reads **no** corpus, so it works with nothing downloaded. |
| `describe_cellarium()` | What this surface is, what the corpus holds, and what is deliberately not exposed. |

The package has 72 read tools. Three are advertised, and that is a decision rather than an omission.

**The reason is that the rigor lives in the system prompt, not in the tools.** Survey the whole corpus
before forming a view; do not anchor on the first design that comes to mind; viability is not growth rate;
a benchmark note is not a measurement; `raw_available=0` does not mean the data is absent. Hand a caller
the raw menu and it reads the first design it thinks of and emits a number with none of the scope caveats
that make the number true — the instrument without the discipline. `ask_cellwright` applies that
discipline on your behalf, and refuses when the corpus cannot support the question.

If you want the menu anyway — you installed the package, so it is your machine and your call:

```bash
CELLARIUM_MCP_EXPOSE_ALL=1
```

That advertises the read and analysis tools alongside the three. It does not grant permission to anything
that was refused; visibility and permission are separate keys, deliberately.

---

## What it will not do, and why

> A third-party agent connected over MCP must not be able to launch a simulation, write to your launch
> queue, fetch from the network, or reach your credential vault, without you agreeing.

That is a **shipped default protecting you from your own agent** — not a wall between you and your data.
This is open source; you can fork the file and delete the checks, and on your machine that is a legitimate
thing to do. What the default guarantees is that it does not happen by accident.

Two tiers, and the difference between them is whether a human gate exists further down:

**Refused, with no environment variable that lifts it.** Nothing approves these after the fact:

| Tool | Why |
|---|---|
| `run_experiment` | Starts a simulation immediately. Unlike the `propose_*` family, there is no approval step behind it. |
| `download_raw` | Fetches from HuggingFace and writes archives — often gigabytes — into your runs directory. |
| `web_get` | Makes outbound HTTP requests. A third-party agent should not originate network traffic from your machine. |
| `use_skill` | Loads external instruction text into the agent loop. That is an instruction-injection surface, not a data read. |

**Refused by default, liftable with `CELLARIUM_MCP_ALLOW_WRITES=1`.** The `propose_experiment`,
`propose_experiments`, `revise_experiment` and `propose_rebuild` family writes drafts into your launch
queue — and that queue *is* the human airlock, so nothing they queue runs until you approve it. They are
still off by default, and specifically not enabled as a side effect of `EXPOSE_ALL`, because the risk is
real rather than theoretical: an automated probe in this repository once wrote eight phantom drafts into
that queue in a single sweep.

**The credential vault is absent by construction rather than by exclusion.** No tool in the package
touches it, and a test fails if one is ever added.

---

## One protocol limitation, stated plainly

MCP's `tools/list` has no way to say *withheld*. An unadvertised tool is indistinguishable, over the wire,
from a tool that was never built — and calling one returns a generic unknown-tool error. That is the
"missing versus withheld" confusion this project keeps finding in itself, here imposed by the protocol
rather than chosen.

There is no proper fix, so there are two partial ones. The withheld names are listed in the server's
**instructions**, which every client receives at initialize time; and `describe_cellarium` reports each
one with its reason and how to lift it if it is liftable.

---

## Before you use a number from here

Three things that are easy to get wrong and are covered at length in the
[dataset datasheet](DATASHEET.md):

1. **These are simulated values, not laboratory measurements.** The model is mechanistic, which makes its
   internal state interesting; it does not make it an observation.
2. **Rows pool only within one arm** — the same fitted knowledge base (`kb_sha256`), operon setting and
   elongation model. Averaging across arms produces a number that describes neither.
3. **A refusal is a result.** When `ask_cellwright` declines, it is reporting something true about the
   corpus. Re-asking in different words will not make the data exist.

---

## Design record

The shape of this surface — one tool rather than a menu, stdio rather than hosted, BYOK, the two refusal
tiers — was decided before it was built and the reasoning is kept in
[Deferred decisions](DECISIONS.md) under **D6**, with the later assessment that revised parts of it under
**D6a**. Implementation: `src/cellarium/mcp.py`; policy tests `tests/test_mcp_surface.py` (no SDK needed);
wiring tests `tests/test_mcp_server_wire.py`.
