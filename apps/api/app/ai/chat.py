"""Grounded codebase Q&A.

Two answer modes, both grounded in analysed artefacts:

* **LLM mode** - the model receives the retrieved evidence (real files, line
  ranges, symbols, endpoints, workflows) and is instructed to use nothing else.
* **Retrieval-only mode** - no key configured: the answer is composed
  extractively from the same evidence, with explicit citations.

Either way, the response carries the citations RepoLens actually used, so the
UI can link every statement back to a file and line.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from repolens_shared.utils import truncate

from ..core.config import Settings
from ..models.tables import Analysis, ApiEndpointRecord, ChatMessageRecord, SymbolRecord, WorkflowRecord
from ..services.impact import impact_summary_lines
from ..services.search import dedupe_by_path, search
from ..services.store import (
    get_architecture,
    get_artifact,
    get_overview,
    list_workflows,
    symbol_references,
)
from .llm import get_llm
from .trace import DbTracer, score_name_match, word_tokens

logger = logging.getLogger(__name__)

MAX_EVIDENCE_CHARS = 22_000
EVIDENCE_BLOCK_CHARS = 1_800

INTENTS = {
    "explain_repo": r"\b(explain|summar|overview|what is this|what does this (repo|project)|describe)\b",
    "how_works": r"\bhow (does|do|is|are)\b.*\b(work|flow|function|implemented)\b",
    "what_happens": r"\bwhat happens when\b|\btrace\b|\bwalk me through\b",
    "where_handled": r"\bwhere (is|are|does)\b.*\b(handled|implemented|defined|located|live)\b|\bfind the (code|file|function)\b",
    "where_used": r"\bwhere (is|are)\b.*\bused\b|\bwho calls\b|\busages?\b|\breferences?\b",
    "impact": r"\bwhat (could|would|might) break\b|\bimpact\b|\bif i (modify|change|refactor|delete)\b|\bsafe to change\b",
    "database": r"\b(database|db|schema|table|model|migration|postgres|mysql|mongo|orm|prisma)\b",
    "api": r"\b(api|endpoint|route|rest|graphql|webhook)\b",
    "tests": r"\btests?\b|\bcoverage\b",
    "quality": r"\b(quality|complexit|coupling|circular|risk|tech debt|refactor)\b",
    "security": r"\b(auth|authentication|authorization|login|jwt|token|permission|security|session)\b",
}


@dataclass
class Evidence:
    path: str
    line: int | None
    label: str
    body: str
    source: str  # retrieval | endpoint | symbol | workflow | artifact
    score: float = 0.0
    symbol: str | None = None

    def to_citation(self) -> dict:
        return {"path": self.path, "line": self.line, "symbol": self.symbol,
                "reason": truncate(self.label, 160), "score": round(self.score, 3)}


@dataclass
class AnswerContext:
    intent: str
    entities: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    trace: dict | None = None
    impact: dict | None = None
    notes: list[str] = field(default_factory=list)


def detect_intent(question: str) -> str:
    lowered = (question or "").lower()
    priority = ["impact", "what_happens", "where_used", "where_handled", "how_works", "explain_repo",
                "database", "api", "tests", "security", "quality"]
    for intent in priority:
        if re.search(INTENTS[intent], lowered):
            return intent
    return "general"


def extract_entities(question: str) -> list[str]:
    """Identifier-ish tokens worth looking up in the symbol/route tables."""
    tokens = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b", question or "")
    stop = {
        "how", "does", "what", "when", "where", "which", "why", "the", "and", "for", "with", "from", "this",
        "that", "work", "works", "repo", "repository", "code", "file", "files", "explain", "happens", "used",
        "used", "into", "have", "are", "is", "in", "to", "of", "a", "an", "do", "need", "change", "modify",
        "break", "implemented", "handled", "defined",
    }
    entities: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in stop or len(lowered) < 3:
            continue
        if token not in entities:
            entities.append(token)
    return entities[:8]


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #

def gather_context(session: Session, settings: Settings, analysis: Analysis, question: str,
                   focus_path: str | None = None) -> AnswerContext:
    intent = detect_intent(question)
    entities = extract_entities(question)
    context = AnswerContext(intent=intent, entities=entities)
    tokens = word_tokens(question)

    # ---- 1. hybrid retrieval over code chunks
    hits = search(session, settings, analysis.id, question, limit=14,
                  paths=[focus_path] if focus_path else None)
    if focus_path and len(hits) < 4:
        hits.extend(search(session, settings, analysis.id, question, limit=10))
    for hit in dedupe_by_path(hits, max_per_path=3)[:10]:
        context.evidence.append(Evidence(path=hit["path"], line=hit["start_line"], symbol=hit.get("symbol"),
                                         label=f"code match ({hit['kind']})", body=hit["snippet"],
                                         source="retrieval", score=hit["score"]))

    # ---- 2. endpoints matching the question
    endpoint_rows = session.execute(
        select(ApiEndpointRecord).where(ApiEndpointRecord.analysis_id == analysis.id).limit(4000)
    ).scalars().all()
    keyword = _keyword_from_question(question)
    scored_endpoints = []
    for row in endpoint_rows:
        text = f"{row.path} {row.handler or ''} {row.controller or ''} {row.service or ''}".lower()
        score = 0.0
        if keyword and keyword in text:
            score += 0.55
        for token in tokens:
            if len(token) > 3 and token in text:
                score += 0.12
        if score > 0:
            scored_endpoints.append((score, row))
    scored_endpoints.sort(key=lambda item: -item[0])
    for score, row in scored_endpoints[:5]:
        body = (f"{row.method} {row.path}\nhandler: {row.handler}\nfile: {row.file_path}:{row.line}\n"
                f"controller: {row.controller}\nservice: {row.service or 'n/a'}\n"
                f"framework: {row.framework or 'n/a'}\nauth: {row.auth_required}")
        context.evidence.append(Evidence(path=row.file_path, line=row.line, symbol=row.handler,
                                         label=f"endpoint {row.method} {row.path}", body=body,
                                         source="endpoint", score=score))

    # ---- 3. symbols matching the entities
    for entity in entities[:5]:
        rows = session.execute(
            select(SymbolRecord).where(SymbolRecord.analysis_id == analysis.id,
                                       func.lower(SymbolRecord.name) == entity.lower()).limit(4)
        ).scalars().all()
        if not rows:
            rows = session.execute(
                select(SymbolRecord).where(SymbolRecord.analysis_id == analysis.id,
                                           func.lower(SymbolRecord.name).like(f"%{entity.lower()}%")).limit(4)
            ).scalars().all()
        for rank, row in enumerate(rows):
            body = (f"{row.kind} {row.name}\nfile: {row.path}:{row.start_line}-{row.end_line}\n"
                    f"signature: {row.signature or 'n/a'}\n"
                    f"{('doc: ' + truncate(row.docstring, 300)) if row.docstring else ''}\n"
                    f"calls: {', '.join(call.get('full') or call.get('name', '') for call in (row.calls or [])[:10])}")
            context.evidence.append(Evidence(path=row.path, line=row.start_line, symbol=row.name,
                                             label=f"symbol {row.name} ({row.kind})", body=body,
                                             source="symbol", score=0.5 - rank * 0.05))
            if intent == "where_used":
                references = symbol_references(session, analysis.id, row.name, limit=8)
                if references:
                    lines = "\n".join(f"- {ref['path']}:{ref['line']} in {ref['symbol']} (via {ref['via']})"
                                      for ref in references)
                    context.evidence.append(Evidence(path=ref["path"] if references else row.path, line=None,
                                                     symbol=row.name,
                                                     label=f"references to {row.name} ({len(references)} found)",
                                                     body=lines, source="symbol", score=0.7))

    # ---- 4. workflows (by keyword, or by traced entities)
    workflow_hits = _match_workflows(session, analysis.id, keyword, tokens, question)
    for workflow in workflow_hits[:3]:
        steps = "\n".join(f"{index}. {step.get('label')} [{step.get('kind')}] "
                         f"{step.get('file_path')}:{step.get('line')}"
                         for index, step in enumerate(workflow["steps"], start=1))
        context.evidence.append(Evidence(
            path=(workflow["steps"][0]["file_path"] if workflow["steps"] and workflow["steps"][0].get("file_path")
                  else workflow.get("files", [""])[0]),
            line=(workflow["steps"][0].get("line") if workflow["steps"] else None),
            label=f"workflow {workflow['name']} [{workflow.get('category') or 'flow'}] (confidence {workflow['confidence']:.0%})",
            body=f"trigger: {workflow.get('trigger')}\nsteps:\n{steps}",
            source="workflow", score=0.65,
        ))
        if intent in {"how_works", "what_happens", "where_handled", "security"} and context.trace is None:
            context.trace = _workflow_as_trace(workflow)

    # ---- 4b. real impact computation when the question is about change risk
    if intent == "impact":
        report, target_path = _impact_for_question(session, analysis, question, entities, focus_path)
        if report is not None and target_path:
            lines = impact_summary_lines(report)
            context.evidence.append(Evidence(
                path=target_path, line=(report.get("target") or {}).get("line"),
                label=f"impact report for {target_path}",
                body="\n".join(lines), source="impact", score=0.95,
            ))
            context.impact = {
                "target": target_path,
                "summary": lines,
                "direct_dependencies": [item["path"] for item in (report.get("direct_dependencies") or [])][:12],
                "dependents": [item["path"] for item in (report.get("dependents") or [])][:12],
                "indirect_dependents": [item["path"] for item in (report.get("indirect_dependents") or [])][:12],
                "affected_endpoints": [
                    {"method": endpoint.get("method"), "path": endpoint.get("path"),
                     "file_path": endpoint.get("file_path"), "line": endpoint.get("line")}
                    for endpoint in (report.get("affected_endpoints") or [])[:15]
                ],
                "affected_workflows": [
                    {"name": workflow.get("name"), "category": workflow.get("category"),
                     "impacted_steps": workflow.get("impacted_steps") or []}
                    for workflow in (report.get("affected_workflows") or [])[:10]
                ],
                "related_tests": [test.get("path") for test in (report.get("related_tests") or [])][:12],
                "risks": (report.get("risks") or [])[:6],
                "notes": report.get("notes") or [],
            }
        elif target_path is None:
            context.notes.append(
                "No concrete file could be identified in the question, so no impact graph was computed. "
                "Mention a file path (for example `backend/app/crud.py`) or open the file in the Code Explorer."
            )

    # ---- 5. deep trace for entity questions
    if context.trace is None and entities and intent in {"how_works", "what_happens", "where_handled", "where_used",
                                                        "security", "general"}:
        tracer = DbTracer(session, analysis.id)
        best: tuple[float, SymbolRecord] | None = None
        for entity in entities[:4]:
            for row in tracer.find_symbols(entity, limit=6):
                score = score_name_match(row.name, tokens)
                if score > 0 and (best is None or score > best[0]):
                    best = (score, row)
        if best is not None:
            trace = tracer.trace(best[1].path, best[1].name)
            if trace["steps"]:
                trace["root"] = {"name": best[1].name, "path": best[1].path, "line": best[1].start_line,
                                 "kind": best[1].kind, "trigger": f"call {best[1].name}()"}
                context.trace = trace
                context.notes.append(
                    f"Traced execution starting from `{best[1].name}` ({best[1].path}:{best[1].start_line})."
                )

    # ---- 6. architecture/overview evidence for broad questions
    if intent in {"explain_repo", "quality", "database", "api", "tests"} or len(context.evidence) < 4:
        overview = get_overview(session, analysis.id)
        digest = _overview_digest(overview)
        context.evidence.append(Evidence(path=(overview.get("repo", {}).get("full_name") or "repository"),
                                         line=None, label="repository overview artefact", body=digest,
                                         source="artifact", score=0.4))
        if intent == "explain_repo":
            architecture = get_architecture(session, analysis.id)
            layers = "\n".join(f"- {layer['label']}: {layer['files']} files, {layer['loc']} LOC "
                               f"({layer['description']})" for layer in architecture.get("layers", []))
            context.evidence.append(Evidence(path="architecture", line=None, label="architecture layers",
                                             body=layers or "No layers detected.", source="artifact", score=0.5))

    context.evidence = _budget(context.evidence)
    return context


def _keyword_from_question(question: str) -> str | None:
    lowered = (question or "").lower()
    for candidate in ("login", "logout", "signup", "register", "auth", "payment", "checkout", "order", "cart",
                      "upload", "search", "user", "product", "invoice", "subscription", "webhook", "notification",
                      "profile", "session", "token", "report", "dashboard", "comment", "post", "message", "file"):
        if re.search(rf"\b{candidate}", lowered):
            return candidate
    return None


# Question vocabulary -> workflow categories / name fragments. This lets
# "how does authentication work?" land on the traced login flow instead of the
# first flow whose name happens to share a word with the question.
DOMAIN_HINTS: dict[str, tuple[set[str], tuple[str, ...]]] = {
    "auth": (
        {"auth", "security"},
        ("login", "token", "password", "auth", "session", "logout", "jwt", "recover", "reset"),
    ),
    "registration": ({"registration"}, ("register", "signup", "sign-up", "user", "account", "invite")),
    "payment": ({"payment"}, ("payment", "checkout", "order", "invoice", "billing", "subscribe")),
    "notification": ({"notification"}, ("email", "notify", "notification", "mail", "message")),
    "crud": ({"crud"}, ("create", "update", "delete", "list", "read", "item", "item", "patch")),
    "background": ({"background"}, ("job", "task", "worker", "queue", "cron", "schedule")),
}

DOMAIN_TRIGGERS: dict[str, tuple[str, ...]] = {
    "auth": ("auth", "login", "log in", "sign in", "signin", "token", "jwt", "password", "credential", "session", "logout", "permission", "role"),
    "registration": ("register", "registration", "sign up", "signup", "onboard", "new user", "create account"),
    "payment": ("payment", "pay", "checkout", "order", "billing", "invoice", "subscription"),
    "notification": ("notification", "notify", "email", "mail", "alert"),
    "crud": ("crud", "create", "update", "delete", "list", "fetch", "save", "item"),
    "background": ("background", "job", "worker", "queue", "scheduled", "cron"),
}


def _domains_for(question: str) -> set[str]:
    lowered = (question or "").lower()
    return {domain for domain, triggers in DOMAIN_TRIGGERS.items() if any(trigger in lowered for trigger in triggers)}


def _match_workflows(session: Session, analysis_id: str, keyword: str | None, tokens: set[str],
                     question: str | None = None) -> list[dict]:
    payload = list_workflows(session, analysis_id, limit=100)
    domains = _domains_for(question or "")
    scored: list[tuple[float, dict]] = []
    lowered_question = (question or "").lower()
    # "how does authentication work" should land on the sign-in flow, not on the
    # password-reset flow, unless the question explicitly asks about resetting.
    generic_auth = "auth" in domains and not any(
        word in lowered_question for word in ("reset", "recover", "forgot", "password", "change")
    )
    for workflow in payload["workflows"]:
        text = (f"{workflow['name']} {workflow.get('trigger') or ''} {workflow.get('description') or ''} "
                f"{workflow.get('category') or ''}").lower()
        score = 0.0
        if generic_auth and any(fragment in text for fragment in ("login", "access-token", "signin", "sign-in", "authenticate")):
            score += 0.3
        for domain in domains:
            categories, fragments = DOMAIN_HINTS[domain]
            if (workflow.get("category") or "") in categories:
                score += 0.6
            if any(fragment in text for fragment in fragments):
                score += 0.35
        if keyword and keyword in text:
            score += 0.8
        for token in tokens:
            if len(token) > 3 and token in text:
                score += 0.15
        if score > 0:
            scored.append((score, workflow))
    scored.sort(key=lambda item: (-item[0], -item[1]["confidence"]))
    return [workflow for _, workflow in scored[:4]]


IMPACT_PATH_RE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_\-.]*(?:/[A-Za-z0-9_\-.*]+)+\.[A-Za-z0-9]{1,8})")
IMPACT_FILE_RE = re.compile(r"\b([A-Za-z0-9_\-]+\.(?:py|ts|tsx|js|jsx|go|rb|java|php|rs|cs|kt|sql))\b")


def _candidate_targets(question: str) -> list[str]:
    """Path-like strings the user may have mentioned, most specific first."""
    candidates: list[str] = []
    for match in IMPACT_PATH_RE.findall(question or ""):
        candidates.append(match)
    for match in IMPACT_FILE_RE.findall(question or ""):
        candidates.append(match)
    for token in extract_entities(question or ""):
        if "/" in token or "." in token:
            candidates.append(token)
    ordered: list[str] = []
    for candidate in candidates:
        cleaned = candidate.strip("`'\".,;:")
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    return ordered


def _impact_for_question(session: Session, analysis: Analysis, question: str, entities: list[str],
                         focus_path: str | None) -> tuple[dict | None, str | None]:
    """Resolve the file the user is asking about and compute its real blast radius."""
    from ..services.impact import build_impact_report, resolve_target_path

    target = None
    for candidate in ([focus_path] if focus_path else []) + _candidate_targets(question):
        if not candidate:
            continue
        target = resolve_target_path(session, analysis.id, candidate)
        if target:
            break
    if target is None:
        # fall back to the most relevant retrieved file for the question
        return None, None

    symbol = None
    for entity in entities:
        if entity.lower() not in target.lower() and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", entity):
            symbol = entity
            break
    try:
        report = build_impact_report(session, analysis.id, target, symbol, depth=3)
    except Exception as exc:  # impact must never break the chat
        logger.warning("impact computation failed for %s: %s", target, exc)
        return None, target
    if report.get("error"):
        return None, target
    return report, target


def _workflow_as_trace(workflow: dict) -> dict:
    steps = workflow.get("steps") or []
    first = steps[0] if steps else {}
    return {
        "root": {"name": workflow.get("entry_point") or first.get("symbol") or workflow["name"],
                 "path": first.get("file_path") or (workflow.get("files") or [""])[0],
                 "line": first.get("line"), "trigger": workflow.get("trigger")},
        "steps": workflow["steps"],
        "truncated": workflow.get("trace_truncated", False),
        "evidence": workflow.get("evidence", []),
        "files": workflow.get("files", []),
        "workflow_id": workflow["id"],
        "confidence": workflow["confidence"],
    }


def _overview_digest(overview: dict) -> str:
    repo = overview.get("repo", {})
    languages = ", ".join(f"{language['label']} ({language['percent']}%)" for language in (overview.get("languages") or [])[:6])
    frameworks = ", ".join(framework["name"] for framework in (overview.get("frameworks") or [])[:10])
    endpoints = overview.get("endpoint_stats", {})
    databases = ", ".join(tech["name"] for tech in (overview.get("databases") or [])[:6])
    lines = [
        f"repository: {repo.get('full_name')}",
        f"description: {repo.get('description') or 'n/a'}",
        f"files: {overview.get('files')} (parsed {overview.get('parsed_files')}, failed {overview.get('failed_files')})",
        f"loc: {overview.get('loc')}",
        f"symbols: {overview.get('symbols')} (functions {overview.get('functions')}, classes {overview.get('classes')})",
        f"languages: {languages or 'n/a'}",
        f"frameworks: {frameworks or 'n/a'}",
        f"endpoints: {overview.get('endpoints')} {endpoints.get('methods') or ''}",
        f"database: {databases or 'n/a'}",
        f"modules: {overview.get('modules')}, dependency edges: {overview.get('edges')}",
        f"circular dependencies: {overview.get('circular_dependencies')}, high-coupling modules: {overview.get('high_coupling_modules')}",
        f"workflows traced: {overview.get('workflows')}, test files: {overview.get('test_files')}",
        f"quality: {overview.get('quality', {}).get('issues')} heuristic findings, health {overview.get('quality', {}).get('health_score')}/100",
    ]
    manifests = overview.get("manifests") or []
    if manifests:
        lines.append("manifests: " + ", ".join(f"{manifest['path']} ({manifest.get('ecosystem')})" for manifest in manifests[:6]))
    top_deps = overview.get("top_dependencies") or []
    if top_deps:
        lines.append("top third-party imports: " + ", ".join(f"{dep['name']} ({dep['imports']})" for dep in top_deps[:10]))
    return "\n".join(lines)


def _budget(evidence: list[Evidence]) -> list[Evidence]:
    """Keep the highest-signal evidence inside the prompt budget."""
    seen: set[tuple[str, int | None, str]] = set()
    unique: list[Evidence] = []
    for item in sorted(evidence, key=lambda entry: -entry.score):
        key = (item.path, item.line, item.source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    budget = MAX_EVIDENCE_CHARS
    out: list[Evidence] = []
    for item in unique:
        size = len(item.body) + 200
        if size > budget:
            continue
        budget -= size
        item.body = truncate(item.body, EVIDENCE_BLOCK_CHARS)
        out.append(item)
    # preserve a stable, readable order (repository-wide first, then code-level)
    order = {"impact": 0, "artifact": 1, "workflow": 2, "endpoint": 3, "symbol": 4, "retrieval": 5}
    out.sort(key=lambda item: (order.get(item.source, 9), -item.score))
    return out[:14]


# --------------------------------------------------------------------------- #
# Answer composition
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """You are RepoLens, an assistant that explains an analysed GitHub repository to a developer.

Hard rules:
1. Use ONLY the EVIDENCE blocks below (and the conversation history). Never invent files, paths, functions,
   endpoints, tables, frameworks or behaviour.
2. Cite the source of every factual claim inline as `path/to/file.ext:line` (or `path/to/file.ext` when the
   line is unknown). Use the exact paths from the evidence.
3. If the evidence does not answer the question, say exactly what is missing and which files would need to be
   inspected. Never guess.
4. Prefer calling out concrete names: files, symbols, endpoints, tables, workflow steps.
5. Be concise and technical. Use short Markdown paragraphs, bullet lists and numbered steps for flows.
6. When a TRACE is provided, base the flow description on it and keep the step order.
"""


def build_answer(session: Session, settings: Settings, analysis: Analysis, question: str,
                 history: list[dict] | None = None, focus_path: str | None = None) -> dict:
    started = time.perf_counter()
    context = gather_context(session, settings, analysis, question, focus_path)
    llm = get_llm(settings)
    notes: list[str] = list(context.notes)

    evidence_text = _render_evidence(context)
    trace_text = _render_trace(context.trace)

    answer_text: str | None = None
    model = "retrieval-only"
    if llm.available:
        history_text = ""
        for turn in (history or [])[-6:]:
            role = "Developer" if turn.get("role") == "user" else "RepoLens"
            history_text += f"{role}: {truncate(turn.get('content', ''), 700)}\n"
        user_prompt = (
            f"REPOSITORY: {analysis.repo_id}\n"
            f"QUESTION: {question}\n\n"
            f"{'CONVERSATION SO FAR:' + chr(10) + history_text if history_text else ''}"
            f"{'FOCUS FILE: ' + focus_path + chr(10) if focus_path else ''}"
            f"\nTRACE (ordered execution steps found by static analysis):\n{trace_text}\n"
            f"\nEVIDENCE:\n{evidence_text}\n\n"
            "Answer the question following the hard rules."
        )
        try:
            answer_text = llm.complete(system=SYSTEM_PROMPT, user=user_prompt)
            if answer_text:
                model = f"{llm.provider}:{llm.model}"
            else:
                notes.append("The configured LLM returned an empty response; falling back to the extractive answer.")
        except Exception as exc:
            logger.warning("LLM chat completion failed: %s", exc)
            notes.append(f"LLM call failed ({type(exc).__name__}); this answer was composed extractively from evidence.")
    else:
        notes.append("No LLM key configured: this answer is composed extractively from retrieved repository evidence.")

    if not answer_text:
        answer_text = _extractive_answer(question, context, analysis, session)
        cited = _citations_in(answer_text, context.evidence)
    else:
        cited = _citations_in(answer_text, context.evidence) or context.evidence[:6]

    citations = [item.to_citation() for item in cited[:12]]
    followups = _followups(context, session, analysis)
    payload = {
        "answer": answer_text.strip(),
        "citations": citations,
        "retrieval": [{"id": item.path, "path": item.path, "symbol": item.symbol, "kind": item.source,
                       "start_line": item.line or 1, "end_line": item.line or 1,
                       "score": round(item.score, 3), "snippet": truncate(item.body, 300)} for item in context.evidence[:10]],
        "trace": context.trace,
        "model": model,
        "grounded": True,
        "llm_configured": bool(llm.available),
        "followups": followups,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "notes": notes,
        "intent": context.intent,
        "impact": context.impact,
        "evidence_count": len(context.evidence),
    }
    _persist_turns(session, analysis.id, question, payload)
    return payload


def _render_evidence(context: AnswerContext) -> str:
    blocks: list[str] = []
    for index, item in enumerate(context.evidence, start=1):
        location = f"{item.path}:{item.line}" if item.line else item.path
        blocks.append(f"[E{index}] {item.label} - {location} (source: {item.source}, score {item.score:.2f})\n"
                      f"{item.body}")
    return "\n\n".join(blocks) if blocks else "(no matching evidence was found in this repository)"


def _render_trace(trace: dict | None) -> str:
    if not trace or not trace.get("steps"):
        return "(no traced execution path - the question is answered from the evidence blocks only)"
    lines = []
    root = trace.get("root") or {}
    if root:
        lines.append(f"root: {root.get('name')} ({root.get('path')}:{root.get('line')}) trigger={root.get('trigger')}")
    for index, step in enumerate(trace["steps"], start=1):
        location = f"{step.get('file_path')}:{step.get('line')}" if step.get("file_path") else "unknown"
        lines.append(f"{index}. {step.get('label')} [{step.get('kind')}] {location} - {step.get('detail') or ''}")
    if trace.get("truncated"):
        lines.append("(trace truncated - deeper hops were not resolvable statically)")
    return "\n".join(lines)


def _citations_in(answer: str, evidence: list[Evidence]) -> list[Evidence]:
    """Order the evidence by the order its path is first mentioned in the answer."""
    positions: dict[str, int] = {}
    for item in evidence:
        needle = item.path
        index = answer.find(needle)
        if index == -1:
            index = answer.find(needle.rsplit("/", 1)[-1])
        if index >= 0:
            positions[item.path] = min(positions.get(item.path, 10**9), index)
    ordered = sorted([item for item in evidence if item.path in positions], key=lambda item: positions[item.path])
    return ordered


def _extractive_answer(question: str, context: AnswerContext, analysis: Analysis, session: Session) -> str:
    """Compose a grounded answer without an LLM."""
    heading = f"### {question.strip()}"
    parts: list[str] = [heading, ""]

    if context.intent == "explain_repo" or (context.intent == "general" and not context.evidence):
        overview = context.evidence[0].body if context.evidence and context.evidence[0].source == "artifact" else ""
        parts.append("This repository was analysed statically; here is what the analysis found:\n")
        parts.append("```\n" + overview + "\n```\n")

    if context.trace and context.trace.get("steps"):
        root = context.trace.get("root") or {}
        confidence = context.trace.get("confidence")
        confidence_text = f", confidence {confidence:.0%}" if isinstance(confidence, (int, float)) and confidence else ""
        parts.append(f"**Traced path starting at `{root.get('name')}` "
                     f"({root.get('path')}:{root.get('line')}{confidence_text}):**")
        parts.append("")
        for index, step in enumerate(context.trace["steps"], start=1):
            location = f"{step.get('file_path')}:{step.get('line')}" if step.get("file_path") else "unresolved"
            parts.append(f"{index}. **{step.get('label')}** — `{location}` _{step.get('kind')}_")
            if step.get("detail"):
                parts.append(f"   - {truncate(str(step['detail']), 160)}")
        if context.trace.get("truncated"):
            parts.append("\n_The trace stopped where static resolution failed (dynamic dispatch or generated code)._")
        parts.append("")

    if context.impact:
        impact = context.impact
        parts.append(f"**Blast radius of `{impact['target']}`**")
        parts.append("")
        for line in impact["summary"]:
            parts.append(f"- {line}")
        parts.append("")
        if impact["affected_endpoints"]:
            parts.append("**Endpoints that can be affected:**")
            for endpoint in impact["affected_endpoints"][:8]:
                parts.append(f"- `{endpoint.get('method')} {endpoint.get('path')}` — `{endpoint.get('file_path')}:{endpoint.get('line')}`")
            parts.append("")
        if impact["affected_workflows"]:
            parts.append("**Workflows that pass through this file:**")
            for workflow in impact["affected_workflows"][:6]:
                steps = ", ".join(str(step.get("label")) for step in (workflow.get("impacted_steps") or [])[:3])
                parts.append(f"- {workflow.get('name')} [{workflow.get('category')}]" + (f" — steps: {steps}" if steps else ""))
            parts.append("")
        if impact["related_tests"]:
            parts.append("**Tests that exercise it:** " + ", ".join(f"`{test}`" for test in impact["related_tests"][:6]))
            parts.append("")
        if impact["risks"]:
            parts.append("**Risks:**")
            for risk in impact["risks"][:5]:
                flag = "heuristic" if risk.get("heuristic") else "measured"
                parts.append(f"- **{risk.get('level')}** — {risk.get('title')}: {risk.get('detail')} _({flag})_")
            parts.append("")

    code_items = [item for item in context.evidence if item.source in {"retrieval", "symbol"}]
    structured = [item for item in context.evidence if item.source in {"endpoint", "workflow", "artifact", "impact"}]

    if structured:
        parts.append("**Repository evidence:**")
        for item in structured[:6]:
            location = f"`{item.path}:{item.line}`" if item.line else f"`{item.path}`"
            parts.append(f"- {item.label} — {location}")
        parts.append("")

    if code_items:
        parts.append("**Relevant code:**")
        for item in code_items[:5]:
            location = f"`{item.path}:{item.line}`"
            title = f" ({item.symbol})" if item.symbol else ""
            parts.append(f"\n{location}{title}")
            parts.append("```")
            parts.append(truncate(item.body, 900))
            parts.append("```")

    if not context.evidence:
        parts.append("No evidence matching this question was found in the analysed repository. "
                     "Try naming a file, symbol, endpoint or concept that exists in the codebase "
                     "(for example: a route path, a class name, or a table name).")
    else:
        parts.append("\n---")
        parts.append(f"_Grounded in {len(context.evidence)} retrieved evidence block(s) from this analysis. "
                     "No LLM key is configured, so this answer quotes the evidence instead of paraphrasing it._")
    return "\n".join(parts)


def _followups(context: AnswerContext, session: Session, analysis: Analysis) -> list[str]:
    suggestions: list[str] = []
    if context.intent != "impact" and context.evidence:
        first = context.evidence[0]
        if first.symbol:
            suggestions.append(f"What could break if I modify `{first.symbol}`?")
        if first.path and first.path.endswith((".py", ".ts", ".tsx", ".js", ".go", ".rb", ".java")):
            suggestions.append(f"Where is `{first.path.rsplit('/', 1)[-1]}` used?")
    workflow_payload = list_workflows(session, analysis.id, limit=6)
    for workflow in workflow_payload["workflows"][:3]:
        suggestions.append(f"How does this work: {workflow.get('trigger') or workflow['name']}?")
    seen: list[str] = []
    for suggestion in suggestions:
        if suggestion not in seen:
            seen.append(suggestion)
    return seen[:4]


def _persist_turns(session: Session, analysis_id: str, question: str, payload: dict) -> None:
    from repolens_shared.utils import stable_id
    timestamp = int(time.time() * 1000)
    session.add(ChatMessageRecord(id=stable_id("chat", analysis_id, question, timestamp), analysis_id=analysis_id,
                                  role="user", content=truncate(question, 4000), citations=[]))
    session.add(ChatMessageRecord(id=stable_id("chat-answer", analysis_id, question, timestamp), analysis_id=analysis_id,
                                  role="assistant", content=payload["answer"], citations=payload["citations"],
                                  model=payload["model"]))
    try:
        session.commit()
    except Exception:
        session.rollback()
