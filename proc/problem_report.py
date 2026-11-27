"""
Relatório de problemas da migração/publicação agrupados por categoria.

Varre ``JournalProc`` / ``IssueProc`` / ``ArticleProc`` de um escopo
(coleção, periódico, ano, fascículo) cujos campos ``*_status`` estão em
``BLOCKED`` ou ``PENDING``, lê os respectivos ``*ProcResult`` em lote e
agrupa os itens por uma "assinatura" do problema, para que a frequência
de cada tipo de problema ajude a priorizar a correção.

Como ``ProcResult.detail`` é JSON livre (sem esquema fixo), a assinatura
é extraída por heurística:

1. procura recursivamente chaves conhecidas (``exception_type``,
   ``exception_message``, ``traceback``, ``error``, ``message``, ...);
2. de um traceback, usa a última linha (``Tipo: mensagem``);
3. normaliza o texto (PIDs, ISSN, números, caminhos, URLs, trechos entre
   aspas viram marcadores) para que ocorrências do mesmo problema em
   itens diferentes caiam na mesma categoria;
4. sem nada reconhecível, usa a "forma" do JSON (chaves de 1º nível).

Como a causa costuma estar registrada num evento anterior ao último, para
cada item são considerados o **primeiro** evento não concluído da
sequência atual (causa provável, usado para categorizar) e o **último**
evento não concluído (sintoma).

O resultado é gerado no idioma de quem o solicitou (en, pt ou es; ver
``resolve_language``) como um ZIP com arquivos CSV padrão (RFC 4180,
UTF-8), um por tabela:

- itens com problemas: uma linha por item (identificado pelo nome, ex.:
  ``rsp v38n2 S0034-89102004000200001 (scl)``, não pelo id do banco), com
  a causa provável e o último problema;
- problemas por item: uma linha por evento com falha de cada item;
- resumo por categoria: categorias ordenadas por frequência (C001 = mais
  frequente), com exemplos de itens;
- status: distribuição dos status no escopo;
- leia-me: escopo, totais e significado das colunas.
"""

import csv
import hashlib
import heapq
import io
import json
import logging
import os
import re
import sys
import tempfile
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict

from django.db.models import Count, Q
from django.utils import timezone

from tracker import choices as tracker_choices

PROBLEM_STATUS = (
    tracker_choices.PROGRESS_STATUS_BLOCKED,
    tracker_choices.PROGRESS_STATUS_PENDING,
)

STATUS_FIELDS = {
    "journal": ["migration_status", "qa_ws_status", "public_ws_status"],
    "issue": [
        "migration_status",
        "files_status",
        "docs_status",
        "qa_ws_status",
        "public_ws_status",
    ],
    "article": [
        "migration_status",
        "xml_status",
        "sps_pkg_status",
        "qa_ws_status",
        "public_ws_status",
    ],
}

# chaves de ``detail`` reconhecidas, por papel
TYPE_KEYS = ("exception_type", "error_type", "exc_type", "type")
MESSAGE_KEYS = (
    "exception_message",
    "error_message",
    "error",
    "errors",
    "exception",
    "exceptions",
    "failures",
    "failure",
    "reason",
    "message",
    "msg",
)
TRACEBACK_KEYS = ("traceback", "exc_traceback", "trace")

MAX_DEPTH = 6
MAX_TEXT = 300
CHUNK_SIZE = 500
EXAMPLES_PER_CATEGORY = 5

KIND_EXCEPTION = "exception"
KIND_UNSUCCESSFUL = "unsuccessful"
KIND_NO_EVENT = "no_failed_event"
KIND_ANALYSIS_ERROR = "analysis_error"

# motivos de relatório incompleto
PARTIAL_TIME = "time"
PARTIAL_ITEMS = "items"
PARTIAL_ERROR = "error"
PARTIAL_MEMORY = "memory"

_NORMALIZATIONS = [
    # tipo de classe: <class 'x.y.Error'>
    (re.compile(r"<class '([^']+)'>"), r"\1"),
    (re.compile(r"https?://\S+"), "<URL>"),
    (re.compile(r"(?:[A-Za-z]:)?(?:/[\w.\-@]+){2,}/?"), "<PATH>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<UUID>"),
    # PID v2 (S + 22) ou v3 (23 alfanuméricos)
    (re.compile(r"\bS\d{4}-\d{3}[\dXx]\d{13}\b"), "<PID>"),
    (re.compile(r"\b[A-Za-z0-9]{23}\b(?=\W|$)"), "<PID>"),
    (re.compile(r"\b\d{4}-\d{3}[\dXx]\b"), "<ISSN>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<HEX>"),
    (re.compile(r"'[^']{1,200}'"), "'<V>'"),
    (re.compile(r'"[^"]{1,200}"'), '"<V>"'),
    (re.compile(r"\d+"), "<N>"),
    (re.compile(r"\s+"), " "),
]


def normalize_text(text, max_length=MAX_TEXT):
    """Transforma uma mensagem concreta em um "molde" comparável."""
    if text is None:
        return ""
    text = str(text)
    for pattern, repl in _NORMALIZATIONS:
        text = pattern.sub(repl, text)
    return text.strip()[:max_length]


def clean_exception_type(value):
    if not value:
        return ""
    value = str(value).strip()
    m = re.match(r"<class '([^']+)'>", value)
    if m:
        value = m.group(1)
    return value[:120]


def last_traceback_line(text):
    """
    Retorna (tipo, mensagem) da última linha significativa de um traceback.
    ``"ValueError: x"`` -> ("ValueError", "x").
    """
    if not text:
        return "", ""
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    # ``format_traceback`` pode ser repr de lista; nesse caso a linha útil
    # costuma estar no fim mesmo
    for line in reversed(lines):
        if line.startswith(("File ", "^", "~", "During handling", "The above")):
            continue
        m = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt|DoesNotExist|MultipleObjectsReturned|[A-Z]\w*))\s*:\s*(.*)$", line)
        if m:
            return m.group(1), m.group(2)
        return "", line
    return "", ""


def _stringify(value):
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _find_values(data, keys, depth=0):
    """Busca em largura por valores não vazios das chaves ``keys``."""
    if depth > MAX_DEPTH:
        return []
    found = []
    if isinstance(data, dict):
        lowered = {str(k).lower(): v for k, v in data.items()}
        for key in keys:
            value = lowered.get(key)
            if value not in (None, "", [], {}):
                found.append(value)
        for value in data.values():
            if isinstance(value, (dict, list)):
                found.extend(_find_values(value, keys, depth + 1))
    elif isinstance(data, list):
        for value in data[:50]:
            if isinstance(value, (dict, list)):
                found.extend(_find_values(value, keys, depth + 1))
    return found


def _first_text(values):
    """Primeiro valor útil; listas/dicts são reduzidos ao 1º elemento."""
    for value in values:
        if isinstance(value, list):
            if not value:
                continue
            value = value[0]
        if isinstance(value, dict):
            # um dict de falhas: tenta extrair a mensagem dele
            sig = extract_signature(value, _depth=1)
            if sig["message"] or sig["exception_type"]:
                return sig["exception_type"], sig["message"]
            value = _stringify(value)
        text = _stringify(value).strip()
        if text:
            return "", text
    return "", ""


def extract_signature(detail, _depth=0):
    """
    Extrai de um ``detail`` arbitrário um dicionário com:
    ``exception_type``, ``message`` (concreta, truncada),
    ``template`` (normalizada) e ``source`` (como foi obtida).
    """
    result = {"exception_type": "", "message": "", "template": "", "source": ""}

    if detail in (None, "", [], {}):
        result["source"] = "empty"
        return result

    if isinstance(detail, str):
        # pode ser um JSON serializado como texto
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, (dict, list)):
                return extract_signature(parsed, _depth)
        except (ValueError, TypeError):
            pass
        exc_type, message = last_traceback_line(detail) if "Traceback" in detail else ("", detail)
        result.update(exception_type=exc_type, message=message, source="text")
    else:
        exc_type = ""
        message = ""
        types = _find_values(detail, TYPE_KEYS)
        if types and isinstance(types[0], str):
            exc_type = clean_exception_type(types[0])

        for value in _find_values(detail, TRACEBACK_KEYS):
            tb_type, tb_message = last_traceback_line(_stringify(value))
            if tb_type or tb_message:
                exc_type = exc_type or tb_type
                message = tb_message
                result["source"] = "traceback"
                break

        msg_type, msg = _first_text(_find_values(detail, MESSAGE_KEYS))
        if msg:
            # mensagem explícita tem precedência sobre a linha do traceback
            message = msg
            result["source"] = "traceback" if result["source"] == "traceback" else "message"
            exc_type = exc_type or msg_type
        elif not message and _depth == 0:
            # sem nada reconhecível: usa a forma do JSON como assinatura
            if isinstance(detail, dict):
                message = "keys: " + ",".join(sorted(str(k) for k in detail.keys())[:20])
            else:
                message = f"list[{len(detail)}]"
            result["source"] = "shape"
        result.update(exception_type=exc_type, message=message)

    result["message"] = (result["message"] or "")[:1000]
    result["template"] = normalize_text(result["message"])
    if not result["exception_type"] and result["template"].startswith("Traceback"):
        result["exception_type"], _ = last_traceback_line(result["message"])
    return result


def normalize_operation(name):
    """Nome de operação sem PIDs / números (ex.: 'register <PID>')."""
    return normalize_text(name or "", max_length=64) or "(sem nome)"


def _event_signature(event):
    sig = extract_signature(event.get("detail"))
    has_exception = bool(sig["exception_type"]) or sig["source"] == "traceback"
    return {
        "operation": event.get("name") or "",
        "operation_template": normalize_operation(event.get("name")),
        "created": event.get("created"),
        "exception_type": sig["exception_type"],
        "message": sig["message"],
        "template": sig["template"],
        "source": sig["source"],
        "kind": KIND_EXCEPTION if has_exception else KIND_UNSUCCESSFUL,
    }


def select_failed_events(events):
    """
    ``events`` em ordem cronológica. Retorna (primeiro_falho, ultimo_falho).
    ``completed`` None/False conta como falho.
    """
    failed = [e for e in events if not e.get("completed")]
    if not failed:
        return None, None
    return failed[0], failed[-1]


def category_key(item_type, problem_fields, root):
    if root is None:
        parts = [item_type, "+".join(problem_fields), KIND_NO_EVENT, "", ""]
    else:
        parts = [
            item_type,
            root["operation_template"],
            root["kind"],
            root["exception_type"],
            root["template"],
        ]
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10], parts


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------


def _scope_filters(item_type, scope, prefix=""):
    """
    Monta o filtro Django por tipo de item a partir do escopo.
    ``prefix`` (ex.: "proc__") aplica o filtro a partir de outro modelo.
    """
    collections = scope.get("collection_acron_list") or []
    journals = scope.get("journal_acron_list") or []
    year = scope.get("publication_year")
    issue_folder = scope.get("issue_folder")

    def f(**kwargs):
        return Q(**{f"{prefix}{k}": v for k, v in kwargs.items()})

    q = Q()
    # antes de tudo: período de atualização do item
    start, end = updated_range(scope)
    if start:
        q &= f(updated__gte=start)
    if end:
        q &= f(updated__lt=end)
    if collections:
        q &= f(collection__acron__in=collections)
    if item_type == "journal":
        if journals:
            q &= f(acron__in=journals)
    elif item_type == "issue":
        if journals:
            q &= f(journal_proc__acron__in=journals)
        if year:
            q &= f(issue__publication_year=str(year))
        if issue_folder:
            q &= f(issue_folder=issue_folder)
    elif item_type == "article":
        if journals:
            q &= f(issue_proc__journal_proc__acron__in=journals)
        if year:
            q &= f(issue_proc__issue__publication_year=str(year))
        if issue_folder:
            q &= f(issue_proc__issue_folder=issue_folder)
    return q


def _parse_moment(value, end=False):
    """
    "AAAA-MM-DD" ou data-hora ISO -> datetime com fuso. Para o fim do
    período, uma data sem hora inclui o dia inteiro (vira o início do dia
    seguinte, usado com ``<``).
    """
    from datetime import date, datetime, time as dtime, timedelta

    if not value:
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime.combine(value, dtime.min)
        if end:
            moment += timedelta(days=1)
    else:
        text = str(value).strip()
        if len(text) == 10:
            moment = datetime.combine(date.fromisoformat(text), dtime.min)
            if end:
                moment += timedelta(days=1)
        else:
            moment = datetime.fromisoformat(text)
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


def updated_range(scope):
    """(início, fim exclusivo) do período de atualização do escopo."""
    return (
        _parse_moment(scope.get("updated_from")),
        _parse_moment(scope.get("updated_to"), end=True),
    )


def _problem_q(item_type, prefix=""):
    q = Q()
    for field in STATUS_FIELDS[item_type]:
        q |= Q(**{f"{prefix}{field}__in": PROBLEM_STATUS})
    return q


# ---------------------------------------------------------------------------
# Capacidade da máquina
# ---------------------------------------------------------------------------
# O desejável é analisar tudo o que está no período. O que limita é a
# capacidade da máquina (tempo e memória do worker); ao chegar perto do
# limite, a coleta para e o relatório sai incompleto, com o que foi obtido.

DEFAULT_MEMORY_LIMIT_MB = 1024


def _cgroup_memory_limit_mb():
    """Limite de memória do container (cgroup v2 ou v1), em MB, ou None."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path) as fp:
                value = fp.read().strip()
        except OSError:
            continue
        if value.isdigit():
            limit = int(value) / (1024 * 1024)
            # valores absurdos significam "sem limite" no cgroup v1
            if limit < 1024 * 1024:
                return limit
    return None


def memory_limit_mb():
    """
    Quanto de memória (MB) o relatório pode usar: o setting
    ``PROBLEM_REPORT_MEMORY_LIMIT_MB``; senão metade do limite do
    container; senão ``DEFAULT_MEMORY_LIMIT_MB``.
    """
    from django.conf import settings

    configured = getattr(settings, "PROBLEM_REPORT_MEMORY_LIMIT_MB", None)
    if configured:
        return float(configured)
    container = _cgroup_memory_limit_mb()
    if container:
        return container / 2
    return float(DEFAULT_MEMORY_LIMIT_MB)


def current_memory_mb():
    """Memória residente atual do processo (MB)."""
    try:
        with open("/proc/self/statm") as fp:
            resident_pages = int(fp.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (OSError, ValueError, IndexError, AttributeError):
        import resource

        # pico (KB no Linux); aproximação quando /proc não existe
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _models():
    from proc.models import (
        ArticleProc,
        ArticleProcResult,
        IssueProc,
        IssueProcResult,
        JournalProc,
        JournalProcResult,
    )

    return {
        "journal": (JournalProc, JournalProcResult),
        "issue": (IssueProc, IssueProcResult),
        "article": (ArticleProc, ArticleProcResult),
    }


def _item_values(item_type):
    base = ["id", "pid", "collection__acron"] + STATUS_FIELDS[item_type]
    if item_type == "journal":
        return base + ["acron", "title"]
    if item_type == "issue":
        return base + ["journal_proc__acron", "issue_folder"]
    return base + [
        "issue_proc__journal_proc__acron",
        "issue_proc__issue_folder",
        "pkg_name",
    ]


def _location(item_type, row):
    if item_type == "journal":
        return row.get("acron") or "", ""
    if item_type == "issue":
        return row.get("journal_proc__acron") or "", row.get("issue_folder") or ""
    return (
        row.get("issue_proc__journal_proc__acron") or "",
        row.get("issue_proc__issue_folder") or "",
    )


def item_name(item_type, collection, journal_acron, issue_folder, pid, pkg_name=None):
    """
    Nome legível do item (em vez do id do banco), no mesmo estilo de
    ``IssueProc.__str__``: ``rsp v38n2 S0034-89102004000200001 (scl)``.
    """
    if item_type == "journal":
        parts = [journal_acron or pid]
    elif item_type == "issue":
        parts = [journal_acron, issue_folder or pid]
    else:
        parts = [journal_acron, issue_folder, pid or pkg_name]
    name = " ".join(p for p in parts if p) or "?"
    return f"{name} ({collection})" if collection else name


def _admin_url(item_type, proc_id):
    from django.conf import settings

    model_name = {"journal": "journalproc", "issue": "issueproc", "article": "articleproc"}[item_type]
    base = (getattr(settings, "WAGTAILADMIN_BASE_URL", "") or "").rstrip("/")
    return f"{base}/admin/snippets/proc/{model_name}/edit/{proc_id}/"


def _iter_chunks(iterable, size):
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class _Stop(Exception):
    """Interrompe a coleta; o relatório sai com o que foi obtido."""

    def __init__(self, reason, detail=""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _soft_time_limit_exception():
    try:
        from celery.exceptions import SoftTimeLimitExceeded

        return SoftTimeLimitExceeded
    except ImportError:  # pragma: no cover
        return _Stop


def collect_problems(
    scope, item_types, deadline=None, max_items=None, memory_limit=None
):
    """
    Retorna um dict com:

    - ``rows``: um dict por item com algum status problemático, com
      ``failed_events`` (eventos não concluídos, em ordem cronológica);
    - ``overview``: distribuição de status;
    - ``categories``: ``{chave: partes}`` de cada categoria encontrada;
    - ``coverage``: ``{tipo: {"total": n, "processed": m}}``;
    - ``partial``: ``None`` ou ``{"reason", "detail"}`` se a coleta parou
      antes do fim.

    Analisa todos os itens com status problemático do escopo (que inclui o
    período de atualização), dos atualizados mais recentemente para os mais
    antigos, intercalando periódicos, fascículos e artigos — se a coleta
    parar antes do fim, o que fica de fora é o mais antigo.

    Relatório incompleto é melhor que nenhum: a coleta para (e devolve o
    que já obteve) ao atingir ``deadline`` (``time.monotonic()``), ao
    atingir ``memory_limit`` (MB residentes) ou ``max_items``, se o celery
    sinalizar o limite de tempo ou se um lote falhar no banco. Erro ao
    analisar um item não interrompe: o item entra como "não foi possível
    analisar".

    Pensado para volume de produção: lê os itens em lotes, busca no banco
    só os eventos com falha (os concluídos, que costumam ter ``detail``
    grande, nem são lidos) e não guarda o ``detail`` — só a assinatura
    extraída dele. Textos repetidos são compartilhados entre as linhas.
    """
    models = _models()
    result = {
        "rows": [],
        "overview": [],
        "categories": {},
        "coverage": {},
        "partial": None,
    }
    rows = result["rows"]
    try:
        streams = []
        for item_type in item_types:
            proc_model, result_model = models[item_type]
            scope_q = _scope_filters(item_type, scope)
            problem_qs = proc_model.objects.filter(scope_q).filter(_problem_q(item_type))
            result["coverage"][item_type] = {"total": problem_qs.count(), "processed": 0}
            result["overview"].extend(_overview(proc_model, item_type, scope_q))
            qs = (
                problem_qs.values("updated", *_item_values(item_type))
                .order_by("-updated", "-id")
                .iterator(chunk_size=CHUNK_SIZE)
            )
            streams.append(_tagged(item_type, qs))

        # os tipos são intercalados pela data de atualização, os mais
        # recentes primeiro: se a coleta parar, fica de fora o mais antigo,
        # seja periódico, fascículo ou artigo
        merged = heapq.merge(*streams, key=lambda entry: entry[0], reverse=True)
        for batch in _iter_chunks(merged, CHUNK_SIZE):
            if deadline is not None and time.monotonic() >= deadline:
                raise _Stop(PARTIAL_TIME)
            if memory_limit is not None:
                used = current_memory_mb()
                if used >= memory_limit:
                    raise _Stop(
                        PARTIAL_MEMORY, f"memory {used:.0f} MB >= {memory_limit:.0f} MB"
                    )
            if max_items is not None and len(rows) >= max_items:
                raise _Stop(PARTIAL_ITEMS, f"max_items={max_items}")
            if max_items is not None:
                batch = batch[: max_items - len(rows)]
            by_type = defaultdict(list)
            for _, item_type, row in batch:
                by_type[item_type].append(row)
            for item_type, chunk in by_type.items():
                _collect_chunk(item_type, models[item_type][1], chunk, rows, result["categories"])
                result["coverage"][item_type]["processed"] += len(chunk)
        if max_items is not None and len(rows) >= max_items:
            if any(c["processed"] < c["total"] for c in result["coverage"].values()):
                raise _Stop(PARTIAL_ITEMS, f"max_items={max_items}")
    except _Stop as stop:
        result["partial"] = {"reason": stop.reason, "detail": stop.detail}
    except _soft_time_limit_exception():
        result["partial"] = {"reason": PARTIAL_TIME, "detail": ""}
    except Exception as e:
        logging.exception("problem report: collection interrupted")
        result["partial"] = {
            "reason": PARTIAL_ERROR,
            "detail": f"{type(e).__name__}: {e}"[:500],
        }

    if result["partial"]:
        # tipos que nem começaram também aparecem na cobertura
        for item_type in item_types:
            if item_type not in result["coverage"]:
                try:
                    proc_model = models[item_type][0]
                    total = (
                        proc_model.objects.filter(_scope_filters(item_type, scope))
                        .filter(_problem_q(item_type))
                        .count()
                    )
                except Exception:
                    total = "?"
                result["coverage"][item_type] = {"total": total, "processed": 0}

    rows.sort(key=lambda r: (r["collection"], r["journal_acron"], r["issue_folder"], r["item_type"], r["item"]))
    return result


def _tagged(item_type, rows):
    """(updated, item_type, row) — função própria para fixar ``item_type``."""
    for row in rows:
        yield row["updated"], item_type, row


def _overview(proc_model, item_type, scope_q):
    items = []
    for field in STATUS_FIELDS[item_type]:
        for item in (
            proc_model.objects.filter(scope_q)
            .values(field)
            .annotate(total=Count("id"))
            .order_by("-total")
        ):
            items.append(
                {
                    "item_type": item_type,
                    "status_field": field,
                    "status": item[field],
                    "total": item["total"],
                }
            )
    return items


def _collect_chunk(item_type, result_model, chunk, rows, categories):
    events_by_proc = defaultdict(list)
    for event in (
        result_model.objects.filter(proc_id__in=[r["id"] for r in chunk])
        .filter(_failed_q())
        .order_by("proc_id", "created", "id")
        .values("proc_id", "name", "detail", "created")
        .iterator(chunk_size=CHUNK_SIZE)
    ):
        # reduz já ao que interessa; o detail (JSON) é descartado
        try:
            signature = _event_signature(event)
        except _soft_time_limit_exception():
            raise
        except Exception as e:
            signature = _analysis_error_signature(event.get("name"), e, event.get("created"))
        events_by_proc[event["proc_id"]].append(signature)
    for row in chunk:
        failed = events_by_proc.pop(row["id"], [])
        try:
            rows.append(_build_row(item_type, row, failed, categories))
        except _soft_time_limit_exception():
            raise
        except Exception as e:
            rows.append(_build_row(
                item_type, row, [_analysis_error_signature("(report)", e)], categories
            ))


def _analysis_error_signature(operation, exc, created=None):
    message = f"{type(exc).__name__}: {exc}"[:1000]
    return {
        "operation": operation or "",
        "operation_template": normalize_operation(operation),
        "created": created,
        "exception_type": type(exc).__name__,
        "message": message,
        "template": normalize_text(message),
        "source": "report",
        "kind": KIND_ANALYSIS_ERROR,
    }


def _failed_q():
    return Q(completed=False) | Q(completed__isnull=True)


def _shared(value):
    return sys.intern(value) if isinstance(value, str) else value


def _compact_event(event, category):
    """Só o necessário para o CSV; textos repetidos compartilhados."""
    return {
        "operation": _shared(event["operation"]),
        "created": event["created"],
        "kind": event["kind"],
        "exception_type": _shared(event["exception_type"]),
        "message": event["message"],
        "category": category,
    }


def _build_row(item_type, row, failed, categories):
    """
    ``failed``: assinaturas (``_event_signature``) dos eventos não
    concluídos do item, em ordem cronológica.
    """
    problem_fields = [
        f for f in STATUS_FIELDS[item_type] if row.get(f) in PROBLEM_STATUS
    ]
    compact = []
    for event in failed:
        key, parts = category_key(item_type, problem_fields, event)
        categories.setdefault(key, tuple(_shared(p) for p in parts))
        compact.append(_compact_event(event, _shared(key)))
    if compact:
        key = compact[0]["category"]
    else:
        key, parts = category_key(item_type, problem_fields, None)
        categories.setdefault(key, tuple(_shared(p) for p in parts))
    root = compact[0] if compact else None
    symptom = compact[-1] if compact else None
    journal_acron, issue_folder = _location(item_type, row)
    collection = row.get("collection__acron") or ""
    return {
        "category": _shared(key),
        "kind": root["kind"] if root else KIND_NO_EVENT,
        "item": item_name(
            item_type, collection, journal_acron, issue_folder,
            row.get("pid"), row.get("pkg_name"),
        ),
        "item_type": item_type,
        "collection": _shared(collection),
        "journal_acron": _shared(journal_acron),
        "issue_folder": _shared(issue_folder),
        "pid": row.get("pid") or "",
        "pkg_name": row.get("pkg_name") or "",
        "problem_status": _shared("; ".join(f"{f}={row[f]}" for f in problem_fields)),
        "root_operation": root["operation"] if root else "",
        "root_exception_type": root["exception_type"] if root else "",
        "root_message": root["message"] if root else "",
        "root_date": _iso(root["created"]) if root else "",
        "last_operation": symptom["operation"] if symptom else "",
        "last_exception_type": symptom["exception_type"] if symptom else "",
        "last_message": symptom["message"] if symptom else "",
        "total_failed_events": len(compact),
        "failed_events": compact,
        "admin_url": _admin_url(item_type, row["id"]),
    }


def _iso(value):
    if not value:
        return ""
    try:
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


# ---------------------------------------------------------------------------
# Agregação
# ---------------------------------------------------------------------------


def summarize(rows, categories):
    """
    Agrupa ``rows`` por categoria, ordenado por frequência, e atribui a
    cada categoria um código legível (C001 = mais frequente), gravado
    também em cada row (``category_code``) e em cada evento falho.
    """
    groups = {}
    for row in rows:
        key = row["category"]
        group = groups.get(key)
        if group is None:
            item_type, operation, kind, exc_type, template = categories[key]
            group = groups[key] = {
                "category": key,
                "item_type": item_type,
                "kind": kind,
                "operation": operation,
                "exception_type": exc_type,
                "message_template": template,
                "total": 0,
                "collections": set(),
                "journals": set(),
                "issues": set(),
                "problem_status": Counter(),
                "examples": [],
                "example_message": row["root_message"],
            }
        group["total"] += 1
        group["collections"].add(row["collection"])
        if row["journal_acron"]:
            group["journals"].add((row["collection"], row["journal_acron"]))
        if row["issue_folder"]:
            group["issues"].add(
                (row["collection"], row["journal_acron"], row["issue_folder"])
            )
        group["problem_status"][row["problem_status"]] += 1
        if len(group["examples"]) < EXAMPLES_PER_CATEGORY:
            group["examples"].append(row["item"])

    summary = []
    for group in groups.values():
        summary.append(
            {
                "category": group["category"],
                "total": group["total"],
                "item_type": group["item_type"],
                "kind": group["kind"],
                "operation": group["operation"],
                "exception_type": group["exception_type"],
                "message_template": group["message_template"],
                "total_collections": len(group["collections"]),
                "total_journals": len(group["journals"]),
                "total_issues": len(group["issues"]),
                "problem_status": "; ".join(
                    f"{k} ({v})" for k, v in group["problem_status"].most_common(5)
                ),
                "example_message": (group["example_message"] or "")[:500],
                "examples": " | ".join(group["examples"]),
            }
        )
    summary.sort(key=lambda g: (-g["total"], -g["total_journals"], g["category"]))

    codes = {}
    for i, group in enumerate(summary, start=1):
        group["code"] = codes[group["category"]] = f"C{i:03d}"
    for row in rows:
        row["category_code"] = codes[row["category"]]
        for event in row["failed_events"]:
            # um evento secundário pode não ser causa raiz de nenhum item
            event["category_code"] = codes.get(event["category"], "")
    return summary


# ---------------------------------------------------------------------------
# Textos do relatório (en / pt / es)
# ---------------------------------------------------------------------------
# Catálogo próprio em vez de gettext: os .mo não são versionados nem
# compilados no build. O relatório sai no idioma de quem o solicitou
# (``resolve_language``).

LANGUAGES = ("en", "pt", "es")

TEXTS = {
    # tabelas (um CSV cada)
    "sheet_readme": {"en": "Read me", "pt": "Leia-me", "es": "Leeme"},
    "sheet_items": {"en": "Items with problems", "pt": "Itens com problemas", "es": "Ítems con problemas"},
    "sheet_events": {"en": "Problems by item", "pt": "Problemas por item", "es": "Problemas por ítem"},
    "sheet_summary": {"en": "Summary by category", "pt": "Resumo por categoria", "es": "Resumen por categoría"},
    "sheet_status": {"en": "Status", "pt": "Status", "es": "Estado"},
    # colunas
    "item": {"en": "Item", "pt": "Item", "es": "Ítem"},
    "item_type": {"en": "Type", "pt": "Tipo", "es": "Tipo"},
    "collection": {"en": "Collection", "pt": "Coleção", "es": "Colección"},
    "journal": {"en": "Journal", "pt": "Periódico", "es": "Revista"},
    "issue": {"en": "Issue", "pt": "Fascículo", "es": "Número"},
    "pid": {"en": "PID", "pt": "PID", "es": "PID"},
    "package": {"en": "Package", "pt": "Pacote", "es": "Paquete"},
    "problem_status": {"en": "Status with problem", "pt": "Status com problema", "es": "Estado con problema"},
    "category": {"en": "Category", "pt": "Categoria", "es": "Categoría"},
    "kind": {"en": "Nature", "pt": "Natureza", "es": "Naturaleza"},
    "root_operation": {"en": "Probable cause: operation", "pt": "Causa provável: operação", "es": "Causa probable: operación"},
    "root_exception": {"en": "Probable cause: exception", "pt": "Causa provável: exceção", "es": "Causa probable: excepción"},
    "root_message": {"en": "Probable cause: message", "pt": "Causa provável: mensagem", "es": "Causa probable: mensaje"},
    "root_date": {"en": "Probable cause: date", "pt": "Causa provável: data", "es": "Causa probable: fecha"},
    "last_operation": {"en": "Last problem: operation", "pt": "Último problema: operação", "es": "Último problema: operación"},
    "last_exception": {"en": "Last problem: exception", "pt": "Último problema: exceção", "es": "Último problema: excepción"},
    "last_message": {"en": "Last problem: message", "pt": "Último problema: mensagem", "es": "Último problema: mensaje"},
    "failed_events": {"en": "Failed events", "pt": "Eventos com falha", "es": "Eventos con fallo"},
    "link": {"en": "Link", "pt": "Link", "es": "Enlace"},
    "seq": {"en": "No.", "pt": "Nº", "es": "N.º"},
    "operation": {"en": "Operation", "pt": "Operação", "es": "Operación"},
    "date": {"en": "Date", "pt": "Data", "es": "Fecha"},
    "exception": {"en": "Exception", "pt": "Exceção", "es": "Excepción"},
    "message": {"en": "Message", "pt": "Mensagem", "es": "Mensaje"},
    "items": {"en": "Items", "pt": "Itens", "es": "Ítems"},
    "journals": {"en": "Journals", "pt": "Periódicos", "es": "Revistas"},
    "issues": {"en": "Issues", "pt": "Fascículos", "es": "Números"},
    "collections": {"en": "Collections", "pt": "Coleções", "es": "Colecciones"},
    "message_template": {"en": "Message (pattern)", "pt": "Mensagem (molde)", "es": "Mensaje (patrón)"},
    "example_message": {"en": "Example message", "pt": "Exemplo de mensagem", "es": "Ejemplo de mensaje"},
    "examples": {"en": "Example items", "pt": "Exemplos de itens", "es": "Ejemplos de ítems"},
    "status_field": {"en": "Status field", "pt": "Campo de status", "es": "Campo de estado"},
    "status": {"en": "Status", "pt": "Status", "es": "Estado"},
    "total": {"en": "Total", "pt": "Total", "es": "Total"},
    # valores
    "type_journal": {"en": "journal", "pt": "periódico", "es": "revista"},
    "type_issue": {"en": "issue", "pt": "fascículo", "es": "número"},
    "type_article": {"en": "article", "pt": "artigo", "es": "artículo"},
    f"kind_{KIND_EXCEPTION}": {
        "en": "exception (likely bug)",
        "pt": "exceção (provável bug)",
        "es": "excepción (probable bug)",
    },
    f"kind_{KIND_UNSUCCESSFUL}": {
        "en": "not completed (likely data)",
        "pt": "não concluído (provável dado)",
        "es": "no concluido (probable dato)",
    },
    f"kind_{KIND_NO_EVENT}": {
        "en": "no failure event",
        "pt": "sem evento de falha",
        "es": "sin evento de fallo",
    },
    # leia-me
    "title": {
        "en": "Migration/publication problem report",
        "pt": "Relatório de problemas de migração/publicação",
        "es": "Informe de problemas de migración/publicación",
    },
    "generated_at": {"en": "Generated at", "pt": "Gerado em", "es": "Generado el"},
    "scope": {"en": "Scope", "pt": "Escopo", "es": "Alcance"},
    "item_types": {"en": "Item types", "pt": "Tipos de item", "es": "Tipos de ítem"},
    "total_items": {
        "en": "Items with BLOCKED/PENDING status",
        "pt": "Itens com status BLOCKED/PENDING",
        "es": "Ítems con estado BLOCKED/PENDING",
    },
    "total_categories": {"en": "Categories", "pt": "Categorias", "es": "Categorías"},
    "meaning": {"en": "Meaning", "pt": "Significado", "es": "Significado"},
    f"meaning_{KIND_EXCEPTION}": {
        "en": "event with exception/traceback; if it affects many journals, probably systematic",
        "pt": "evento com exceção/traceback; se atinge muitos periódicos, provavelmente sistemático",
        "es": "evento con excepción/traceback; si afecta a muchas revistas, probablemente sistemático",
    },
    f"meaning_{KIND_UNSUCCESSFUL}": {
        "en": "event not completed, without exception; tends to indicate a data problem",
        "pt": "evento não concluído sem exceção; tende a indicar problema de dados",
        "es": "evento no concluido sin excepción; tiende a indicar un problema de datos",
    },
    f"meaning_{KIND_NO_EVENT}": {
        "en": "problem status without a recorded failure event on the item",
        "pt": "status problemático sem evento de falha registrado no item",
        "es": "estado con problema sin evento de fallo registrado en el ítem",
    },
    f"kind_{KIND_ANALYSIS_ERROR}": {
        "en": "could not be analyzed",
        "pt": "não foi possível analisar",
        "es": "no se pudo analizar",
    },
    f"meaning_{KIND_ANALYSIS_ERROR}": {
        "en": "error while building the report for this item (see message); the item has a problem status",
        "pt": "erro ao montar o relatório deste item (ver mensagem); o item tem status problemático",
        "es": "error al construir el informe de este ítem (ver mensaje); el ítem tiene estado con problema",
    },
    "incomplete": {
        "en": "INCOMPLETE REPORT",
        "pt": "RELATÓRIO INCOMPLETO",
        "es": "INFORME INCOMPLETO",
    },
    f"partial_{PARTIAL_TIME}": {
        "en": "the time limit was reached; it contains the most recently updated items analyzed until then",
        "pt": "o limite de tempo foi atingido; contém os itens atualizados mais recentemente, analisados até então",
        "es": "se alcanzó el límite de tiempo; contiene los ítems actualizados más recientemente, analizados hasta entonces",
    },
    f"partial_{PARTIAL_ITEMS}": {
        "en": "the maximum number of items per report was reached; it contains the most recently updated items",
        "pt": "o número máximo de itens por relatório foi atingido; contém os itens atualizados mais recentemente",
        "es": "se alcanzó el número máximo de ítems por informe; contiene los ítems actualizados más recientemente",
    },
    f"partial_{PARTIAL_MEMORY}": {
        "en": "the memory available for the report was reached; it contains the most recently updated items analyzed until then",
        "pt": "a memória disponível para o relatório foi atingida; contém os itens atualizados mais recentemente, analisados até então",
        "es": "se alcanzó la memoria disponible para el informe; contiene los ítems actualizados más recientemente, analizados hasta entonces",
    },
    f"partial_{PARTIAL_ERROR}": {
        "en": "an error interrupted the analysis; it contains the items analyzed until then",
        "pt": "um erro interrompeu a análise; contém os itens analisados até então",
        "es": "un error interrumpió el análisis; contiene los ítems analizados hasta entonces",
    },
    "partial_hint": {
        "en": "the older items of the period were not analyzed: fix the most frequent problems or narrow the period/scope (collection, journal, year) and generate it again",
        "pt": "os itens mais antigos do período não foram analisados: corrija os problemas mais frequentes ou reduza o período/escopo (coleção, periódico, ano) e gere novamente",
        "es": "los ítems más antiguos del período no se analizaron: corrija los problemas más frecuentes o reduzca el período/alcance (colección, revista, año) y genere de nuevo",
    },
    "coverage": {"en": "Analyzed", "pt": "Analisados", "es": "Analizados"},
    "updated_between": {
        "en": "Items updated between",
        "pt": "Itens atualizados entre",
        "es": "Ítems actualizados entre",
    },
    "of": {"en": "of", "pt": "de", "es": "de"},
    "sheets": {"en": "Files", "pt": "Arquivos", "es": "Archivos"},
    "desc_items": {
        "en": "one row per item: probable cause (1st failed event) and last problem",
        "pt": "uma linha por item: causa provável (1º evento com falha) e último problema",
        "es": "una fila por ítem: causa probable (1.er evento con fallo) y último problema",
    },
    "desc_events": {
        "en": "one row per failed event of each item, in chronological order",
        "pt": "uma linha por evento com falha de cada item, em ordem cronológica",
        "es": "una fila por evento con fallo de cada ítem, en orden cronológico",
    },
    "desc_summary": {
        "en": "categories sorted by frequency (C001 = most frequent)",
        "pt": "categorias ordenadas por frequência (C001 = mais frequente)",
        "es": "categorías ordenadas por frecuencia (C001 = la más frecuente)",
    },
    "desc_status": {
        "en": "distribution of status values in the scope",
        "pt": "distribuição dos status no escopo",
        "es": "distribución de los estados en el alcance",
    },
    "tip": {"en": "Tip", "pt": "Dica", "es": "Consejo"},
    "tip_text": {
        "en": "filter the Category column in the item files to see all items with the same problem",
        "pt": "filtre a coluna Categoria nos arquivos de itens para ver todos os itens de um mesmo problema",
        "es": "filtre la columna Categoría en los archivos de ítems para ver todos los ítems con el mismo problema",
    },
}


def t(key, lang):
    entry = TEXTS[key]
    return entry.get(lang) or entry["en"]


# (chave do título, chave do dado, largura)
ITEMS_COLUMNS = [
    ("item", "item", 45),
    ("item_type", "item_type_label", 11),
    ("collection", "collection", 9),
    ("journal", "journal_acron", 12),
    ("issue", "issue_folder", 12),
    ("pid", "pid", 24),
    ("package", "pkg_name", 28),
    ("problem_status", "problem_status", 30),
    ("category", "category_code", 10),
    ("kind", "kind_label", 24),
    ("root_operation", "root_operation", 28),
    ("root_exception", "root_exception_type", 22),
    ("root_message", "root_message", 70),
    ("root_date", "root_date", 19),
    ("last_operation", "last_operation", 28),
    ("last_exception", "last_exception_type", 22),
    ("last_message", "last_message", 70),
    ("failed_events", "total_failed_events", 10),
    ("link", "admin_url", 12),
]

EVENTS_COLUMNS = [
    ("item", "item", 45),
    ("item_type", "item_type_label", 11),
    ("collection", "collection", 9),
    ("journal", "journal_acron", 12),
    ("issue", "issue_folder", 12),
    ("pid", "pid", 24),
    ("problem_status", "problem_status", 30),
    ("seq", "seq", 5),
    ("operation", "operation", 30),
    ("date", "created", 19),
    ("kind", "kind_label", 24),
    ("exception", "exception_type", 22),
    ("message", "message", 90),
    ("category", "category_code", 10),
]

SUMMARY_COLUMNS = [
    ("category", "code", 10),
    ("items", "total", 8),
    ("journals", "total_journals", 10),
    ("issues", "total_issues", 10),
    ("collections", "total_collections", 9),
    ("item_type", "item_type_label", 11),
    ("kind", "kind_label", 24),
    ("operation", "operation", 28),
    ("exception", "exception_type", 22),
    ("message_template", "message_template", 70),
    ("problem_status", "problem_status", 40),
    ("example_message", "example_message", 70),
    ("examples", "examples", 70),
]

OVERVIEW_COLUMNS = [
    ("item_type", "item_type_label", 11),
    ("status_field", "status_field", 18),
    ("status", "status", 10),
    ("total", "total", 10),
]

MAX_CELL = 32000  # limite do Excel/LibreOffice é 32767 caracteres por célula
_ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")
# conteúdo começando com estes caracteres é interpretado como fórmula por
# planilhas (e é vetor de "CSV injection"); prefixa-se com apóstrofo
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _label_rows(rows, lang):
    """Linhas com rótulos traduzidos de tipo e natureza (gerador; não copia a lista)."""
    for row in rows:
        row = dict(row)
        item_type = row.get("item_type")
        if item_type:
            row["item_type_label"] = t(f"type_{item_type}", lang)
        if row.get("kind"):
            row["kind_label"] = t(f"kind_{row['kind']}", lang)
        yield row


def safe_text(value):
    """
    Texto aceito por qualquer aplicativo de planilha: sem caracteres de
    controle inválidos em XML, até ``MAX_CELL`` caracteres e sem ser
    interpretado como fórmula.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    value = _ILLEGAL_XML_CHARS.sub("", value)[:MAX_CELL]
    if value.startswith(_FORMULA_PREFIXES) and not _is_number(value):
        value = "'" + value
    return value


def _is_number(value):
    try:
        float(value)
        return True
    except ValueError:
        return False


def event_rows(rows):
    """
    Uma linha por evento com falha de cada item (sem eventos: 1 linha).
    Gerador: as linhas são produzidas à medida que o CSV é gravado.
    """
    for row in rows:
        base = {k: row[k] for k in (
            "item", "item_type", "collection", "journal_acron",
            "issue_folder", "pid", "problem_status",
        )}
        if not row["failed_events"]:
            yield {
                **base, "seq": "", "operation": "", "created": "",
                "kind": KIND_NO_EVENT, "exception_type": "",
                "message": "", "category_code": row["category_code"],
            }
            continue
        for seq, event in enumerate(row["failed_events"], start=1):
            yield {
                **base,
                "seq": seq,
                "operation": event["operation"],
                "created": _iso(event["created"]),
                "kind": event["kind"],
                "exception_type": event["exception_type"],
                "message": event["message"],
                "category_code": event.get("category_code", ""),
            }


def _readme_rows(data, lang):
    rows, summary, scope, item_types = data["rows"], data["summary"], data["scope"], data["item_types"]
    kinds = Counter(r["kind"] for r in rows)
    lines = [[t("title", lang)]]
    partial = data.get("partial")
    if partial:
        lines += [
            [],
            [t("incomplete", lang), t(f"partial_{partial['reason']}", lang)],
            ["", t("partial_hint", lang)],
        ]
        if partial.get("detail"):
            lines.append(["", partial["detail"]])
    lines += [
        [],
        [t("generated_at", lang), _iso(data["generated_at"])],
        [t("scope", lang), json.dumps(scope, ensure_ascii=False, default=str)],
        [
            t("updated_between", lang),
            f"{scope.get('updated_from') or '…'} — {scope.get('updated_to') or '…'}",
        ],
        [t("item_types", lang), ", ".join(t(f"type_{i}", lang) for i in item_types)],
        [t("total_items", lang), len(rows)],
        [t("total_categories", lang), len(summary)],
    ]
    for item_type, cov in (data.get("coverage") or {}).items():
        lines.append([
            f"{t('coverage', lang)}: {t(f'type_{item_type}', lang)}",
            f"{cov['processed']} {t('of', lang)} {cov['total']}",
        ])
    lines += [
        [],
        [t("kind", lang), t("items", lang), t("meaning", lang)],
    ]
    for kind in (KIND_EXCEPTION, KIND_UNSUCCESSFUL, KIND_NO_EVENT, KIND_ANALYSIS_ERROR):
        lines.append([t(f"kind_{kind}", lang), kinds.get(kind, 0), t(f"meaning_{kind}", lang)])
    lines += [
        [],
        [t("sheets", lang)],
        [t("sheet_items", lang), t("desc_items", lang)],
        [t("sheet_events", lang), t("desc_events", lang)],
        [t("sheet_summary", lang), t("desc_summary", lang)],
        [t("sheet_status", lang), t("desc_status", lang)],
        [],
        [t("tip", lang), t("tip_text", lang)],
    ]
    return lines


def _tables(data, lang):
    """[(kind, chave do título, colunas, linhas)] na ordem de saída."""
    return [
        ("items", "sheet_items", ITEMS_COLUMNS, _label_rows(data["rows"], lang)),
        ("events", "sheet_events", EVENTS_COLUMNS, _label_rows(event_rows(data["rows"]), lang)),
        ("summary", "sheet_summary", SUMMARY_COLUMNS, _label_rows(data["summary"], lang)),
        ("status", "sheet_status", OVERVIEW_COLUMNS, _label_rows(data["overview"], lang)),
        ("readme", "sheet_readme", None, _readme_rows(data, lang)),
    ]


FILE_KINDS = ("items", "events", "summary", "status", "readme")


def _values(columns, row):
    return [safe_text(row.get(key, "")) for _, key, _ in columns]


def _ascii_slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _write_csv(stream, header, rows):
    """
    CSV padrão (RFC 4180): UTF-8 com BOM (para o Excel reconhecer a
    codificação), separador vírgula, aspas duplas, quebra de linha CRLF.
    Grava linha a linha em ``stream`` (binário).
    """
    text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
    writer = csv.writer(text, lineterminator="\r\n")
    if header:
        writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    text.flush()
    text.detach()


def write_zip(data, lang, fileobj):
    """
    Grava em ``fileobj`` um ZIP com um CSV por tabela, no idioma ``lang``,
    linha a linha (sem montar os CSVs inteiros na memória). Nomes internos
    em ASCII, numerados na ordem de leitura sugerida.
    Retorna a lista de nomes dos CSVs.
    """
    names = []
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as zf:
        for number, (kind, title_key, columns, rows) in enumerate(_tables(data, lang), start=1):
            filename = f"{number}-{_ascii_slug(t(title_key, lang))}.csv"
            with zf.open(filename, "w", force_zip64=True) as stream:
                if columns is None:
                    _write_csv(stream, None, ([safe_text(v) for v in line] for line in rows))
                else:
                    _write_csv(
                        stream,
                        [t(c[0], lang) for c in columns],
                        (_values(columns, row) for row in rows),
                    )
            names.append(filename)
    return names


def resolve_language(language_code=None, user=None):
    """
    Idioma do relatório (en, pt ou es) a partir de, em ordem:
    ``language_code`` informado (ex.: idioma ativo no admin), idioma
    preferido do usuário no Wagtail, idioma ativo, ``LANGUAGE_CODE``.
    """
    from django.conf import settings
    from django.utils.translation import get_language

    code = language_code
    if not code and user is not None:
        try:
            code = user.wagtail_userprofile.preferred_language
        except Exception:
            code = None
    code = (code or get_language() or settings.LANGUAGE_CODE or "en").lower()
    prefix = code.split("-")[0].split("_")[0]
    return prefix if prefix in LANGUAGES else "en"


def build_report(
    scope,
    item_types,
    language="en",
    generated_at=None,
    time_budget=None,
    max_items=None,
    memory_limit=None,
):
    """
    Coleta, agrega e grava os CSVs no idioma ``language``, num ZIP.

    Retorna (fileobj, stats): ``fileobj`` é um arquivo temporário (já no
    início) com o ZIP — feche-o após usar; ``stats`` contém totais, os nomes
    dos CSVs, a cobertura, ``partial`` (motivo, se incompleto) e as
    principais categorias (para o admin).

    ``time_budget`` (s), ``memory_limit`` (MB) e ``max_items`` limitam a
    coleta; ao atingi-los o relatório sai incompleto, com o que foi obtido
    (ver ``collect_problems``).
    """
    language = language if language in LANGUAGES else "en"
    generated_at = generated_at or timezone.now()
    deadline = time.monotonic() + time_budget if time_budget is not None else None
    collected = collect_problems(
        scope, item_types, deadline=deadline, max_items=max_items, memory_limit=memory_limit
    )
    rows = collected["rows"]
    summary = summarize(rows, collected["categories"])
    data = {
        "scope": scope,
        "item_types": item_types,
        "generated_at": generated_at,
        "rows": rows,
        "summary": summary,
        "overview": collected["overview"],
        "coverage": collected["coverage"],
        "partial": collected["partial"],
    }
    fileobj = tempfile.TemporaryFile()
    try:
        filenames = write_zip(data, language, fileobj)
        fileobj.seek(0)
    except Exception:
        fileobj.close()
        raise

    stats = {
        "language": language,
        "files": filenames,
        "partial": collected["partial"],
        "coverage": collected["coverage"],
        "total_items": len(rows),
        "total_categories": len(summary),
        "by_kind": dict(Counter(r["kind"] for r in rows)),
        "by_item_type": dict(Counter(r["item_type"] for r in rows)),
        "top_categories": [
            {
                k: g[k]
                for k in (
                    "code",
                    "total",
                    "total_journals",
                    "item_type",
                    "kind",
                    "operation",
                    "exception_type",
                    "message_template",
                    "examples",
                )
            }
            for g in summary[:20]
        ],
    }
    return fileobj, stats
