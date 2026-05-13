---
title: "An Oracle DBA builds AI: shipping Oracle 23ai RAG and an MCP server in a weekend"
published: false
description: An Oracle Apps DBA spends a weekend building two open-source AI projects on top of Oracle 23ai. Five bugs taught me more than any tutorial would have.
tags: oracle, ai, rag, mcp
cover_image: https://raw.githubusercontent.com/shopsmartai/oracle-ebs-rag/main/docs/architecture-dalle.png
canonical_url:
---

I asked Claude to `DROP TABLE` on my Oracle database.

It tried. The guardrails refused. The audit log captured it.

That's the demo screenshot at the top of [`mcp-oracle-dba`](https://github.com/shopsmartai/mcp-oracle-dba), one of two open-source repos I shipped this weekend as an Oracle Apps DBA learning AI infrastructure. The other is [`oracle-ebs-rag`](https://github.com/shopsmartai/oracle-ebs-rag) — a retrieval-augmented chat assistant over Oracle E-Business Suite resolution notes, running on Oracle Database 23ai's native vector search.

Both repos are MIT-licensed. Datasets are fully synthetic.

This post is about what I learned. Not the tutorial-level "here's how to call an embedding API" stuff — the actual production-shaped lessons that took an hour of head-scratching each. If you're an Oracle DBA watching AI from the sidelines, my hope is this post saves you those hours.

---

## Why an Oracle DBA, of all people

The 2026 narrative is "AI is replacing DBAs." Look at any tech-jobs Twitter thread and you'll find it.

The reality I've found is closer to **"DBAs who can ship AI infrastructure replace DBAs who can't."** Production AI is mostly infrastructure: connection pooling, statement timeouts, audit logs, schema allowlists, PII redaction, prompt caching, cost monitoring. Every one of those is something DBAs already think about daily. It's *not* ML research.

I'm an Oracle Apps DBA. Day job is running production Oracle E-Business Suite R12.2 — upgrades, cloning, patching, `adop` troubleshooting, performance tuning, plus database administration on Oracle 19c. Ansible for automation. OCI for cloud. Standard stack.

What surprised me about building AI infrastructure: my Oracle skills transferred more cleanly than I expected. The new piece is *small* compared to the production-engineering scaffolding around it.

Here's the proof, then the lessons.

---

## What I built

### Talk to EBS — RAG over Oracle E-Business Suite

A chat interface where I ask plain-English questions about EBS production scenarios and the system responds with grounded answers and inline citations to the source notes.

{% youtube PnlbIypTfsc %}

The stack:

- **Oracle Database 23ai Free** in Docker (via OrbStack on Apple Silicon). Native `VECTOR(1024, FLOAT32)` datatype, `VECTOR_DISTANCE` function with cosine similarity. **No external vector database. No Pinecone, no Weaviate, no Milvus.**
- **Cohere `embed-english-v3.0`** for embeddings (1024 dimensions, free tier is generous).
- **Claude Sonnet** with prompt caching for grounded generation.
- **Streamlit** chat UI with streaming responses, citations panel, and a sidebar that tracks live cost and prompt-cache hit rate.
- **`uv`** for Python project management.

The dataset is 3 synthetic resolution notes covering concurrent-manager troubleshooting, workflow mailer issues, and `adop` patching failures. Each note has YAML frontmatter and is split on Markdown H2 headings (Symptom / Diagnosis / Root cause / Resolution) into 5–6 chunks. That's about 17 chunks total in the vector store.

Eval harness with Claude Haiku as judge over a 10-question golden set. Current baseline:

| Metric | Result |
|---|---|
| Retrieval recall @ 6 | **100 %** |
| Must-contain pass | **100 %** |
| Must-not-contain pass | **100 %** |
| Claude Haiku judge avg | **4.80 / 5** |

CI regression gate in `.github/workflows/eval.yml` fails the build on >5 percentage-point drop on any metric. Zero tolerance on `must_not_contain` (forbidden-claim violations).

### mcp-oracle-dba — A Model Context Protocol server for Oracle

This one is the more unusual project. MCP is a protocol Anthropic released that lets any compatible client (Claude Desktop, Claude Code, Cursor) plug in tools written in any language. Most "let your LLM query the database" demos hand the LLM a connection string and trust it not to call `DROP TABLE`. This server flips that.

![mcp-oracle-dba demo](https://raw.githubusercontent.com/shopsmartai/mcp-oracle-dba/main/docs/demo.png)

*Above: real conversation through Claude Desktop. Claude runs `list_schemas`, `describe_table`, `run_select` against my Oracle 23ai — then is refused when it tries to `DROP TABLE`. The rejection lands in `audit.log` as a JSON line.*

Five tools exposed:

```
list_schemas       → returns the allowlist of schemas the server can query
describe_table     → column metadata for SCHEMA.TABLE
run_select         → executes a SELECT / WITH, row-capped, PII-redacted
explain_plan       → returns DBMS_XPLAN.DISPLAY output
top_sql            → top SQL by elapsed time from v$sql in the last N min
```

Five independent guardrail layers reject unsafe input before it reaches Oracle:

1. **Single-statement parser** — rejects `... ; DROP TABLE x` injection.
2. **First-keyword allowlist** — only `SELECT` and `WITH` accepted.
3. **Banned-keyword scan** — DML, DDL, PL/SQL blocks, transaction control blocked anywhere in the statement.
4. **Dangerous-package regex** — blocks `DBMS_*`, `UTL_*`, `SYS.*` calls (think `DBMS_LOCK.sleep`, `UTL_HTTP.request`).
5. **Hard row cap** — every approved query gets wrapped in `SELECT * FROM (...) FETCH FIRST :N ROWS ONLY`.

Plus a read-only DB user, schema allowlist for introspection, PII column redaction by name substring (`SSN`, `SALARY`, `PASSWORD`…), JSON audit log of every call, and server-side statement timeout via `oracledb`'s `call_timeout`.

There are 45 security tests in `tests/test_guardrails.py`. Every test maps to a real attack vector. Sample:

```python
@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM dual; DROP TABLE fnd_user",
    "BEGIN dbms_lock.sleep(60); END;",
    "SELECT dbms_random.value FROM dual",
    "SELECT utl_http.request('http://attacker.com') FROM dual",
    "MERGE INTO target USING source ON (...) WHEN MATCHED THEN UPDATE...",
])
def test_blocks_dangerous_sql(sql):
    with pytest.raises(SqlGuardError):
        validate_select(sql)
```

When I wired the MCP server up to Claude Desktop and asked Claude to drop a table, this is what the audit log captured:

```json
{"ts": "2026-05-13T01:07:39Z", "tool": "run_select",
 "sql": "DROP TABLE ragapp.rag_documents",
 "rejected": "Only SELECT and WITH allowed; got: DROP"}
```

Claude got back a clean error message and reported to me that the operation was refused. No SQL ever reached Oracle.

---

## The five bugs that taught me the most

Here's the meat. Each of these cost me about an hour. If you build something similar, you'll likely hit at least two of them.

### 1. OrbStack's macOS port-forward NAT silently mangles Oracle TNS handshakes

Symptom: `python-oracledb` thin-mode connection from my Mac to the Oracle container fails immediately with:

```
oracledb.exceptions.DatabaseError: DPY-4011: the database or
network closed the connection
[Errno 54] Connection reset by peer
```

The listener's text trace log shows nothing — only successful `sqlplus` connections from inside the container. After half an hour of trying `127.0.0.1` vs `localhost`, OOB disable, TNS descriptor format, and force-registering the service, the smoking gun finally surfaced in the *XML* listener alert log (different file from the trace log):

```
* (ADDRESS=(PROTOCOL=tcp)(HOST=192.168.215.0)(PORT=63905))
* <unknown connect data> * 12537
TNS-12537: TNS:connection closed
TNS-12560: Database communication protocol error
TNS-00507: Connection closed
```

`<unknown connect data>` — the listener received the connect packet but couldn't parse it. The source IP was OrbStack's NAT gateway (`.215.0`), not my host or the container.

**The fix:** don't go through `127.0.0.1` at all. OrbStack on macOS gives each container an `<container-name>.orb.local` hostname that routes natively without NAT. So:

```python
# Before — fails
DSN = "127.0.0.1:1521/FREEPDB1"

# After — works
DSN = "oracle23ai.orb.local:1521/FREEPDB1"
```

Same Oracle, same Python, same code path. Different DNS path. Connection succeeds.

This is documented exactly zero places I could find. Filed it under "things you only learn by hitting them."

### 2. Sandboxed macOS apps can't resolve `*.orb.local`

This bit me a second time, an hour later. After getting my terminal scripts to work with `oracle23ai.orb.local`, I wired the MCP server into Claude Desktop and watched `list_schemas` succeed but `run_select` fail with the same `No route to host` error.

Why? Claude Desktop is a sandboxed macOS app. When it spawns the MCP server as a child process, that child process inherits the sandbox — and the sandbox doesn't have access to OrbStack's DNS resolver. So `oracle23ai.orb.local` doesn't resolve.

**The fix:** use the container's direct IP, which routes through normal kernel networking:

```bash
CONTAINER_IP=$(docker inspect oracle23ai \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
# Then: ORA_DSN=$CONTAINER_IP:1521/FREEPDB1
```

The IP can change on container recreate, but it's stable across restarts. For a dev tool, that's a fair trade.

This one is now in the README's troubleshooting section. I expect every Mac user who wires up an MCP server with a Dockerised Oracle to hit this.

### 3. `SELECT_CATALOG_ROLE` replaces three explicit V$ grants

My first cut of the read-only user setup had this:

```sql
CREATE USER mcp_ro IDENTIFIED BY "...";
GRANT CREATE SESSION TO mcp_ro;
GRANT SELECT ON v_$sql       TO mcp_ro;  -- fails
GRANT SELECT ON v_$session   TO mcp_ro;  -- fails
GRANT SELECT ON v_$pdbs      TO mcp_ro;  -- fails
```

Three `ORA-00942: table or view does not exist` errors. The `V_$` views are owned by `SYS`. `SYSTEM` has the DBA role and can read them, but to *grant* them onward you need to be `SYS` or have explicit `WITH GRANT OPTION`. None of those things are true by default.

**The fix:**

```sql
GRANT SELECT_CATALOG_ROLE TO mcp_ro;
```

That one role covers every `V$` and `DBA_*` view in the dictionary, in one line. It's the right answer for any service that needs to introspect Oracle. No `SYS`-grantor problem.

Bonus: the same script also tried `GRANT CREATE INDEX TO ragapp` — which fails because `CREATE INDEX` isn't a system privilege for tables you own; it's implicit with `CREATE TABLE`. Common muscle-memory error from PostgreSQL or MySQL.

### 4. sqlparse tags CTE statements as `Keyword.CTE`, not `DML`

My SQL guardrail had this strict check:

```python
from sqlparse.tokens import DML

first_token = next((t for t in stmt.tokens if not t.is_whitespace), None)
if first_token.ttype is not DML or first_token.value.upper() not in {"SELECT", "WITH"}:
    raise SqlGuardError("Only SELECT and WITH allowed")
```

The unit test I'd written deliberately included `WITH t AS (SELECT 1 FROM dual) SELECT * FROM t` to make sure CTEs would pass. It failed on the first run.

Reason: sqlparse classifies `WITH` as `Token.Keyword.CTE` (a subtype of `Keyword`), *not* `Token.Keyword.DML`. My type check rejected it.

**The fix:** stop relying on token type for the first-keyword check and lean on the other guardrails:

```python
first_val = first_token.value.upper().strip()
if first_val not in {"SELECT", "WITH"}:
    raise SqlGuardError(...)
```

The banned-keyword scan and dangerous-package regex handle the rest. Multi-layer defence means the first-keyword check doesn't need to be perfect at token-type discrimination — it just needs to recognise legitimate SQL starters.

What I like about this one: the test caught the bug in seconds. I didn't have to discover it in production with a real CTE-using user. That's the value of a guardrail test suite.

### 5. Prompt caching doesn't help on first turns. Only follow-ups.

I'd read about Anthropic's prompt caching dropping costs ~85 % and assumed I'd see that immediately. First eval run, all ten questions: `cache_read_input_tokens: 0` across the board. Cost was $0.10 for the run.

What I missed: each question retrieves a *different* set of context chunks. The cached prefix (system prompt + retrieved context) is different per question, so every first turn writes to the cache, none read from it.

Where caching actually fires is **multi-turn follow-ups on the same retrieval**. Ask "concurrent request stuck — what do I check?" then "what about OPP memory pressure?" → the second turn reuses the same retrieved context → cache hit, ~85 % cost drop on the cached portion.

I added a sidebar widget to the Streamlit UI that tracks the live cache hit rate. Now I can *see* the cache working when I ask follow-ups in the same chat. Without that visibility I'd have assumed it wasn't working.

The Anthropic docs are clear about this; I just didn't read carefully enough. The lesson: instrument cost and cache metrics from day one, not as a later optimisation.

---

## What the numbers look like in practice

Per question over the 10-question golden eval:

- Input tokens: ~900–1,500
- Output tokens: ~400–600
- Cost on Claude Sonnet: ~$0.01 per question
- On follow-ups with cache hit: ~$0.002 per question
- Retrieval latency (brute-force VECTOR_DISTANCE on 17 chunks): under 50 ms

The HNSW vector index is intentionally deferred. Oracle 23ai's HNSW needs `vector_memory_size > 0` which requires a database restart. For 17 chunks, brute force is so fast that adding HNSW would be premature optimisation. It's a future blog post — "before/after benchmark when the corpus grows to 10,000 chunks."

---

## What I'd do differently if I started over

A few honest self-critiques after sitting with the result for a day:

- **More synthetic notes from the start.** Three is enough to prove the pipeline, but for eval-driven iteration you really want 15–20. I'll grow the dataset over the next few weekends.
- **Hybrid retrieval would have been worth the day.** Pure vector search has a known weakness: it doesn't always rank obvious keyword matches first. Adding Oracle Text BM25 in parallel and ranking on a combined score is a 20 % retrieval recall improvement on most datasets. Will be the next thing I build.
- **The MCP server should have AWR/ASH tools from day one.** The whole point of an Oracle MCP server is to let an LLM read production diagnostics. Top SQL is in there now; AWR snapshot summary, ASH wait-event histogram, and DB time-model breakdown all belong in the next release.
- **CI should run the eval on every PR, not just locally.** It does now — added `.github/workflows/eval.yml` — but the secrets aren't configured yet so it'll fail on first PR until I add them. Tomorrow problem.

---

## The DBA-to-AI take-away

If you're an Oracle DBA reading this, three points to leave you with:

1. **The vector database you might be evaluating in 2026 is already in Oracle.** Native `VECTOR` datatype since 23ai (released 2024). If your shop runs Oracle, your data is already where the embeddings should live. Single SQL surface, single security model, single backup story.

2. **Production-AI is mostly the production part.** Connection pooling, statement timeouts, audit logs, schema allowlists, PII redaction, prompt caching — these are day-one DBA instincts. Most AI tutorials are written by people who haven't carried a pager and it shows.

3. **Pick a real workload and embed an LLM next to it.** Don't try to compete with ML researchers. The leverage for DBAs is using AI to make existing data more accessible. A RAG assistant over your team's existing runbooks is a higher-ROI weekend project than learning PyTorch.

The job market in 2026 isn't "DBA versus AI engineer." It's "DBA who can ship AI infrastructure versus everyone else." The data depth is the moat. The AI piece sits on top.

---

## Repos and links

- **Talk to EBS** (RAG demo): [github.com/shopsmartai/oracle-ebs-rag](https://github.com/shopsmartai/oracle-ebs-rag)
- **mcp-oracle-dba** (MCP server): [github.com/shopsmartai/mcp-oracle-dba](https://github.com/shopsmartai/mcp-oracle-dba)

Both MIT-licensed. Dataset is fully synthetic. If you're an Oracle person working on similar things, my DMs are open — happy to compare notes. If you're a recruiter working on senior roles in AI / data infrastructure or Oracle + cloud automation, also happy to chat.

Feedback on the post welcome in the comments. Roast me on anything I got wrong.
