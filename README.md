# AI-Powered Customer Support Bot (RAG + Intent)

## 1) what this solves

* ❓ Users repeat the same questions → long queues, SLA breaches.
* 🧭 Agents struggle to find the right answer across PDFs/KB/Confluence.
* 🌍 Need multilingual answers without rewriting the KB.

**Outcomes**

* Deflect 40–70% of L1 tickets.
* Faster first response/ resolution (FRT/MTTR).
* Structured insights on “what users ask” → better docs and product.

## 2) who uses it

* External customers (website widget, in-app help).
* Internal support agents (agent-assist sidebar).
* Success/Docs teams (analytics to improve FAQs).

## 3) top use cases

* FAQ/How-to answers (“reset password”, “invoice download”).
* Order/account lookups via secure backend calls.
* Policy/plan comparisons (grounded in your docs).
* Handover to human with full conversation + retrieval trace.

## 4) architecture (high level)

```
[Client Widget/Chat UI]
        |
   [FastAPI API Gateway]
        |
   ┌─────────── Core Services ───────────┐
   | [Intent Classifier]                 |
   | [RAG Orchestrator]                  |
   |  - Retrievers (BM25 + Vectors)      |
   |  - Re-ranking (optional)            |
   |  - Answer Synth + Citations         |
   | [Tools/Actions] (Order, Reset, etc) |
   └─────────────────────────────────────┘
        |
[Postgres/Mongo]  [Vector DB (Qdrant/PGVector)]
        |
 [Document Ingestion + Embeddings Pipeline]
        |
     [Admin Console + Analytics]
```

## 5) tech stack (pragmatic picks)

* **Backend API**: Python **FastAPI** (typed, async, great perf), Pydantic, Uvicorn/Gunicorn.
* **RAG**: LlamaIndex or LangChain (pick one), **Qdrant** or PostgreSQL + **pgvector**.
* **Embeddings**: text-embedding-3-large (or local bge-m3 if strictly OSS).
* **LLM**: gpt-4.1-mini (cost/quality sweet spot) or OSS (Llama-3.1-8B) for private.
* **Intent classification**:

  * v1: Lightweight zero-shot (LLM prompt) + rules.
  * v2: Fine-tuned small model (scikit-learn or fastText) if volume justifies.
* **DB**:

  * Choose **Postgres** if you want joins + analytics + pgvector.
  * Choose **MongoDB** if you prefer schemaless docs. (I’d do **Postgres + pgvector**.)
* **UI**:

  * MVP: **Gradio/Streamlit** (ship fast).
  * Prod: Your **React** skills for a polished web widget + agent console.
* **Auth & Secrets**: OAuth/JWT, AWS Secrets Manager.
* **Infra**: Docker, docker-compose; then AWS ECS/EKS or Azure Container Apps.
* **MLOps**: Prefect/Celery (ingestion), MLflow for model versions, OpenTelemetry + Prometheus/Grafana for traces/metrics.
* **i18n**: translation API (batch translate KB once) + on-the-fly translate user query/answer (v1).

## 6) data model (Postgres example)

**Tables**

* `faq(doc_id, title, body_md, url, language, source, updated_at)`
* `embedding(doc_id, chunk_id, vector, text, metadata jsonb)`
* `conversation(id, user_id, channel, created_at)`
* `message(id, conversation_id, role, text, intent, answer_latency_ms, created_at)`
* `retrieval_log(message_id, doc_id, score, rerank_score, chunk_preview)`
* `action_log(message_id, action_name, status, payload jsonb)`
* `feedback(message_id, rating int, comment text)`

## 7) RAG flow (how answers are produced)

1. **Detect intent** (billing, technical, account, small-talk).
2. **If action needed** (e.g., “reset password”), call a tool (secure backend API).
3. **Else**: build a search query → hybrid retrieval (BM25 + vector).
4. **Optional**: rerank top-k with a cross-encoder (bge-reranker).
5. **Synthesize** answer with **citations** and safety guardrails.
6. **Translate** output to user’s language (if needed).
7. **Log** conversation + retrieval trace; collect feedback.

## 8) multilingual strategy

* v1: On-the-fly translate (user→EN, answer→user_lang).
* v2: Pre-translate the KB to top N languages and **embed per-language** for better retrieval quality.

## 9) quality guardrails & metrics

* **Hallucination control**: “answer only from sources; if unsure → ask to clarify or escalate.”
* **Citations**: show top 2–3 sources.
* **PII/PIB/Security**: redaction + allowlist tools only.
* **KPIs**: deflection rate, CSAT/Thumbs-up, avg FRT, answer groundedness (manual audits), coverage per intent.

## 10) implementation plan (solo dev, realistic)

**Total**: ~3–5 weeks for a strong MVP you can demo; 8–10 weeks to polish, scale, and add analytics.

### Phase 0 (Day 0. repo + scaffolding) — 0.5 week

* Monorepo or 2 repos:

  * `support-bot-api` (FastAPI)
  * `support-bot-ui` (Streamlit/React)
* Docker, pre-commit (ruff, black, mypy), pytest, Makefile, CI.

### Phase 1 (Ingestion & Vectorization) — 1 week

* Markdown/HTML/PDF loaders (docs, Zendesk exports, Confluence pages).
* Chunking (by headings + tokens ~512–1024).
* Embeddings + upsert to pgvector/Qdrant.
* Re-ingest on file change; hash-based dedupe.
* Admin CLI to list sources, stats.

### Phase 2 (RAG API + Intent) — 1–1.5 weeks

* `/chat` endpoint:

  * classify intent (LLM zero-shot + small rules).
  * retrieval (hybrid), optional rerank, synthesize with citations.
  * guardrails + escalation message when low confidence.
* Tools/actions framework (dependency-injected functions; e.g., `get_order_status(order_id)`).
* Logging tables + OpenTelemetry traces.

### Phase 3 (UI + Feedback) — 0.5–1 week

* MVP chat (Streamlit/Gradio) + thumbs up/down + view citations.
* Simple React widget (optional) to embed on any site.
* Feedback endpoint wires to `feedback` table.

### Phase 4 (Multilingual + Analytics) — 0.5–1 week

* Translate user input/output (LangChain translation or API).
* Basic analytics dashboard (queries by intent, deflection, top missing docs).

### Phase 5 (Hardening) — 1 week

* Tests (≥85% coverage on orchestrator & retriever), load test, rate limiting.
* Secrets, authn (JWT), org-tenant scoping.
* Helm charts or ECS task defs; staging + prod configs.

> If you only have **nights/weekends**, double the durations.

## 11) minimal API contract (FastAPI)

* `POST /chat` → `{messages:[...], lang?: "en", user_id, org_id}` → `{answer, citations, intent, took_ms, trace_id}`
* `POST /feedback` → `{message_id, rating, comment}`
* `POST /ingest` (admin) → upload docs or URLs
* `GET /analytics/summary` (admin)

## 12) intent classifier (v1 → v2)

* **v1**: LLM prompt (few-shot) + fallback to regex rules for high-precision intents (billing, status).
* **v2**: Train a small supervised model: `scikit-learn` (linear SVM/LogReg) on labeled transcripts; export with joblib; integrate as first step (fast & cheap).

## 13) retrieval recipe (solid defaults)

* Hybrid: `BM25 (pg_trgm or Elastic)` + `vector(top_k=30)` → **merge + dedupe** → **rerank top 8** → context window.
* Chunk size 700–900 tokens with 10–20% overlap.
* Store **title, section path, url** for clean citations.

## 14) security & data privacy (must-haves)

* Tenant isolation (org_id everywhere).
* PII masking in logs.
* Tooling uses allowlisted backends; never accept tool names from user content.
* Per-org limits & rate limiting (slow-loris protection).

## 15) evaluation & acceptance criteria

* ≥60% deflection on seeded FAQ set.
* ≥0.8 groundedness (manual rubric) on 50 sampled answers.
* ≤2s p95 for retrieval + answer stub (stream output early).
* Zero critical security findings from a basic threat model.

## 16) repo structure (suggested)

```
support-bot-api/
  app/
    main.py
    deps.py
    routers/
      chat.py
      admin.py
      feedback.py
    core/
      settings.py
      logging.py
    rag/
      ingest.py
      retriever.py
      rerank.py
      orchestrator.py
      tools.py
      prompts.py
    ml/
      intent_zero_shot.py
      intent_model.py
    db/
      models.py
      schemas.py
      migrations/
  tests/
  Dockerfile
  pyproject.toml
support-bot-ui/  (Streamlit or React)
```

## 17) nice-to-have add-ons

* **Agent assist** mode (shows top docs + macro suggestions).
* **Workflow actions** (refund, generate ticket) with confirmations.
* **Grounded extractive answers** toggle (span extraction vs generative).

## 18) risks & mitigations

* **Hallucination** → strict “answer-from-context” prompts, show citations, low-confidence escalate.
* **Doc drift** → nightly re-ingestion, checksum checks.
* **Latency** → cache embeddings, pre-compute BM25 index, stream tokens.
* **Multilingual recall** → per-language embeddings in v2.

---

## your learning path (hands-on)

**Week 1**

* Stand up FastAPI + pgvector locally (docker-compose).
* Implement ingestion for Markdown & URLs. Create embeddings, query via `top_k`.

**Week 2**

* Build `/chat`: hybrid retrieval + simple LLM answer + citations.
* Add thumbs feedback + logging.

**Week 3**

* Add intent (zero-shot), one secure tool (mock `get_order_status`).
* Ship Streamlit UI; record a demo.

**Week 4**

* Add translation, analytics page, tests + CI, basic load test.
* Optional: swap Streamlit → React widget.

<!-- 
//to up both FE & BE
docker compose build
docker compose up 

//to create requirement file
pip freeze > requirements.txt

//.venv activate
cd C:\Projects\Priyanka\AI-Customer-Support-Chatbot\apps\backend
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\activate
$env:DATABASE_URL = "sqlite:///./local.db"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reloa
-->