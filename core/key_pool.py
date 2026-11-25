"""Pool de chaves de API (Groq e Gemini) com rodízio, backoff e fallback automático.

Uso típico (nos nós do grafo):

    from core.key_pool import get_key_pool

    pool = get_key_pool()
    verdict = pool.invoke_groq_structured(messages, GuardrailVerdict)  # Nós 1 e 3
    texto = pool.invoke_gemini_chat(messages)                          # Nó 2

Use sempre ``get_key_pool()`` em vez de instanciar ``KeyPoolManager()`` direto:
o rodízio só distribui a carga se todas as threads compartilharem o mesmo pool.

As chaves (e overrides opcionais ``GROQ_MODEL`` / ``GEMINI_MODEL``) são lidas, nesta
ordem, de ``os.environ`` (carregado de ``.env`` via ``load_dotenv()``) e de
``st.secrets`` (Streamlit Community Cloud).
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import random
import re
import threading
import time
from typing import Any, Callable, Optional, Sequence

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from pydantic import BaseModel

logger = logging.getLogger(__name__)

GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
GEMINI_DEFAULT_MODEL = "gemini-3.5-flash-lite"

# De 1 até 3 chaves gratuitas por provedor (GROQ_API_KEY_1..3 / GEMINI_API_KEY_1..3).
MAX_KEYS_PER_PROVIDER = 3

# Tempo máximo (s) de cada chamada HTTP individual.
REQUEST_TIMEOUT_S = 40

# Retentativas entre passagens completas do pool (somente quando TODAS as chaves falham):
# - Erros transitórios (503 / timeout / rede): espera curta (2 s, 5 s).
# - Rate limit por minuto (429 / RPM): espera adaptativa usando Retry-After (teto 60 s)
#   ou fallback progressivo (20 s, 40 s), dando tempo para a janela de 1 minuto virar.
TRANSIENT_BACKOFF_S: tuple[float, ...] = (2.0, 5.0)
RATE_LIMIT_BACKOFF_S: tuple[float, ...] = (20.0, 40.0)
MAX_RATE_LIMIT_WAIT_S = 60.0

_RETRY_AFTER_PATTERNS = (
    re.compile(r"retry\s+(?:in|after)\s+(\d+(?:\.\d+)?)\s*s", re.IGNORECASE),
    re.compile(r"try\s+again\s+in\s+(\d+(?:\.\d+)?)\s*s", re.IGNORECASE),
    re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", re.IGNORECASE),
)
_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class KeyPoolError(RuntimeError):
    """Pool sem chaves configuradas ou todas as chaves falharam."""


def _read_setting(name: str) -> Optional[str]:
    """Lê uma variável de os.environ e, se não achar, de st.secrets."""
    value: Any = os.environ.get(name)
    if not (isinstance(value, str) and value.strip()):
        value = None
        try:
            import streamlit as st

            value = st.secrets.get(name)
        except Exception:  # sem secrets.toml, fora do Streamlit etc.
            value = None
    if isinstance(value, str) and value.strip():
        return value.strip().strip('"').strip("'")
    return None


def _collect_keys(numbered_prefix: str, singular_names: Sequence[str]) -> list[str]:
    """Junta ``<prefixo>_1..3``; se não houver nenhuma, aceita o nome no singular."""
    keys = [
        key
        for i in range(1, MAX_KEYS_PER_PROVIDER + 1)
        if (key := _read_setting(f"{numbered_prefix}_{i}"))
    ]
    if not keys:
        for name in singular_names:
            key = _read_setting(name)
            if key:
                keys.append(key)
                break
    return list(dict.fromkeys(keys))  # remove duplicadas mantendo a ordem


def _message_text(message: Any) -> str:
    """Extrai o texto de uma resposta de chat (``content`` pode ser str ou lista de blocos)."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


def _status_code(exc: Exception) -> Optional[int]:
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    response = getattr(exc, "response", None)
    val = getattr(response, "status_code", None)
    return val if isinstance(val, int) else None


def _classify_error(exc: Exception) -> str:
    """Classifica o erro em ``rate_limit``, ``transient``, ``permanent`` ou ``other``."""
    code = _status_code(exc)
    cls_name = type(exc).__name__.lower()
    text = f"{cls_name} {exc}".lower()

    if code == 429 or any(
        token in text
        for token in (
            "429",
            "rate limit",
            "rate_limit",
            "ratelimit",
            "resource_exhausted",
            "too many requests",
            "quota",
            "requests per minute",
            "tokens per minute",
        )
    ):
        return "rate_limit"

    if code in (500, 502, 503, 504) or any(
        token in text
        for token in (
            "503",
            "502",
            "504",
            "unavailable",
            "high demand",
            "overloaded",
            "timeout",
            "timed out",
            "connection",
            "temporarily",
            "service unavailable",
        )
    ):
        return "transient"

    if code in (400, 401, 403, 404) or any(
        token in text
        for token in (
            "404",
            "401",
            "403",
            "not_found",
            "not found",
            "modelnotfound",
            "no longer available",
            "invalid_api_key",
            "invalid api key",
            "authentication",
            "permission_denied",
            "permission denied",
            "badrequesterror",
        )
    ):
        return "permanent"

    return "other"


def _extract_retry_after_s(exc: Exception) -> Optional[float]:
    """Tenta ler o tempo de espera sugerido pela API (cabeçalho Retry-After ou mensagem)."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw is not None:
            try:
                seconds = float(raw)
                if seconds > 0:
                    return min(seconds + 1.0, MAX_RATE_LIMIT_WAIT_S)
            except (TypeError, ValueError):
                pass

    text = str(exc)
    for pattern in _RETRY_AFTER_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                seconds = float(match.group(1))
                if seconds > 0:
                    return min(seconds + 1.0, MAX_RATE_LIMIT_WAIT_S)
            except ValueError:
                pass
    return None


def _ensure_json_instruction(
    prompt_messages: Any, pydantic_schema: type[BaseModel]
) -> Any:
    """Garante a palavra 'JSON' e as chaves esperadas nas mensagens para ``json_object``."""
    fields = list(pydantic_schema.model_fields.keys())
    hint = (
        "Responda EXCLUSIVAMENTE com um objeto JSON válido contendo exatamente "
        f"as chaves: {json.dumps(fields, ensure_ascii=False)}."
    )
    if not isinstance(prompt_messages, Sequence) or isinstance(prompt_messages, (str, bytes)):
        return prompt_messages

    msgs = list(prompt_messages)
    if msgs and isinstance(msgs[0], SystemMessage):
        existing = str(msgs[0].content)
        msgs[0] = SystemMessage(content=f"{existing}\n\n{hint}")
    else:
        msgs.insert(0, SystemMessage(content=hint))
    return msgs


def _parse_json_to_model(raw_text: str, pydantic_schema: type[BaseModel]) -> BaseModel:
    """Extrai o objeto JSON da resposta textual e valida no schema Pydantic."""
    cleaned = (raw_text or "").strip()
    fence = _CODE_FENCE_RE.match(cleaned)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        return pydantic_schema.model_validate_json(cleaned)
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            return pydantic_schema.model_validate_json(cleaned[start : end + 1])
        raise


class KeyPoolManager:
    """Rodízio thread-safe (round-robin) de chaves, com backoff inteligente e fallback."""

    def __init__(self) -> None:
        load_dotenv()  # não sobrescreve variáveis já definidas no ambiente
        self._groq_keys = _collect_keys("GROQ_API_KEY", ("GROQ_API_KEY",))
        self._gemini_keys = _collect_keys("GEMINI_API_KEY", ("GOOGLE_API_KEY",))
        self._default_groq_model = _read_setting("GROQ_MODEL") or GROQ_DEFAULT_MODEL
        self._default_gemini_model = _read_setting("GEMINI_MODEL") or GEMINI_DEFAULT_MODEL
        self._lock = threading.Lock()
        # Os ciclos sorteiam o ÍNDICE da chave inicial de cada chamada.
        self._groq_cycle = itertools.cycle(range(len(self._groq_keys)))
        self._gemini_cycle = itertools.cycle(range(len(self._gemini_keys)))

    # ------------------------------------------------------------------ info
    @property
    def groq_key_count(self) -> int:
        return len(self._groq_keys)

    @property
    def gemini_key_count(self) -> int:
        return len(self._gemini_keys)

    @property
    def default_groq_model(self) -> str:
        return self._default_groq_model

    @property
    def default_gemini_model(self) -> str:
        return self._default_gemini_model

    # --------------------------------------------------------------- rodízio
    def _attempt_order(self, provider: str) -> list[int]:
        """Índices das chaves na ordem de tentativa: começa na próxima do rodízio."""
        if provider == "groq":
            keys, cycle, label = self._groq_keys, self._groq_cycle, "Groq"
            hint = "GROQ_API_KEY_1..3 (ou GROQ_API_KEY)"
        else:
            keys, cycle, label = self._gemini_keys, self._gemini_cycle, "Gemini"
            hint = "GEMINI_API_KEY_1..3 (ou GOOGLE_API_KEY)"
        if not keys:
            raise KeyPoolError(
                f"Nenhuma chave {label} configurada. Defina {hint} no .env "
                "ou em st.secrets."
            )
        with self._lock:
            start = next(cycle)
        return [(start + offset) % len(keys) for offset in range(len(keys))]

    def _scrub(self, text: str) -> str:
        """Garante que nenhuma chave apareça em logs ou mensagens de erro."""
        for key in (*self._groq_keys, *self._gemini_keys):
            text = text.replace(key, "***")
        return text

    def _run_with_retries(
        self,
        provider: str,
        label: str,
        keys: list[str],
        invoke_fn: Callable[[str], Any],
    ) -> Any:
        """Percorre o pool inteiro e, se todas as chaves falharem por erro transitório/429,
        aguarda o backoff adequado antes de repetir apenas nas chaves ainda saudáveis.
        """
        order = self._attempt_order(provider)
        dead_indices: set[int] = set()
        transient_waits = 0
        rate_limit_waits = 0
        last_errors: list[str] = []

        while True:
            active_order = [idx for idx in order if idx not in dead_indices]
            if not active_order:
                break

            last_errors = []
            round_categories: list[str] = []
            retry_after_hints: list[float] = []

            for position, idx in enumerate(active_order, start=1):
                try:
                    return invoke_fn(keys[idx])
                except Exception as exc:
                    category = _classify_error(exc)
                    round_categories.append(category)
                    if category == "permanent":
                        dead_indices.add(idx)
                    elif category == "rate_limit":
                        hint_s = _extract_retry_after_s(exc)
                        if hint_s is not None:
                            retry_after_hints.append(hint_s)

                    detail = self._scrub(f"{type(exc).__name__}: {exc}")[:200]
                    last_errors.append(f"chave #{position}: {detail}")
                    if position < len(active_order):
                        logger.warning(
                            "%s: chave #%d/%d falhou (%s); tentando a próxima.",
                            label,
                            position,
                            len(active_order),
                            type(exc).__name__,
                        )

            # Todas as chaves ativas falharam nesta passagem. Decide se vale esperar e tentar de novo.
            remaining = [idx for idx in order if idx not in dead_indices]
            if not remaining:
                break

            if "rate_limit" in round_categories and rate_limit_waits < len(RATE_LIMIT_BACKOFF_S):
                wait_s = (
                    min(retry_after_hints)
                    if retry_after_hints
                    else RATE_LIMIT_BACKOFF_S[rate_limit_waits]
                )
                wait_s = min(wait_s + random.uniform(0.3, 1.5), MAX_RATE_LIMIT_WAIT_S)
                rate_limit_waits += 1
                logger.warning(
                    "%s: rate limit (429) em todas as chaves ativas; aguardando %.1fs (tentativa %d/%d).",
                    label,
                    wait_s,
                    rate_limit_waits,
                    len(RATE_LIMIT_BACKOFF_S),
                )
                time.sleep(wait_s)
                continue

            if "transient" in round_categories and transient_waits < len(TRANSIENT_BACKOFF_S):
                wait_s = TRANSIENT_BACKOFF_S[transient_waits] + random.uniform(0.2, 0.8)
                transient_waits += 1
                logger.warning(
                    "%s: indisponibilidade temporária (503/timeout); aguardando %.1fs (tentativa %d/%d).",
                    label,
                    wait_s,
                    transient_waits,
                    len(TRANSIENT_BACKOFF_S),
                )
                time.sleep(wait_s)
                continue

            break

        raise KeyPoolError(
            f"Todas as {len(order)} chave(s) {label} falharam. " + " | ".join(last_errors)
        )

    # ----------------------------------------------------------------- Groq
    def invoke_groq_structured(
        self,
        prompt_messages: Any,
        pydantic_schema: type[BaseModel],
        model_name: Optional[str] = None,
    ) -> BaseModel:
        """Chama a Groq pedindo saída estruturada SEM usar Tool Calling.

        1ª tentativa: ``method="json_schema"`` (Structured Outputs nativo da Groq).
        Fallback interno: ``response_format={"type": "json_object"}`` + parse/validação
        manual com Pydantic (somente se o erro for de formato/schema, não de rede/429/401).
        """
        effective_model = model_name or self._default_groq_model

        def _call_one(api_key: str) -> BaseModel:
            llm = ChatGroq(
                api_key=api_key,
                model=effective_model,
                temperature=0.0,
                timeout=REQUEST_TIMEOUT_S,
                max_retries=0,  # quem retenta é o pool
            )
            try:
                result = llm.with_structured_output(
                    pydantic_schema, method="json_schema"
                ).invoke(prompt_messages)
                if result is None:
                    raise ValueError("a Groq devolveu uma resposta estruturada vazia")
                return result
            except Exception as primary_exc:
                # Erros de cota, indisponibilidade ou autenticação vão direto para outra chave/backoff.
                if _classify_error(primary_exc) in ("rate_limit", "transient") or _status_code(
                    primary_exc
                ) in (401, 403, 404):
                    raise
                logger.warning(
                    "Groq: method='json_schema' falhou (%s); acionando fallback JSON manual.",
                    type(primary_exc).__name__,
                )
                fallback_llm = ChatGroq(
                    api_key=api_key,
                    model=effective_model,
                    temperature=0.0,
                    timeout=REQUEST_TIMEOUT_S,
                    max_retries=0,
                    model_kwargs={"response_format": {"type": "json_object"}},
                )
                json_messages = _ensure_json_instruction(prompt_messages, pydantic_schema)
                raw_text = _message_text(fallback_llm.invoke(json_messages))
                return _parse_json_to_model(raw_text, pydantic_schema)

        return self._run_with_retries("groq", "Groq", self._groq_keys, _call_one)

    # --------------------------------------------------------------- Gemini
    def invoke_gemini_chat(
        self,
        prompt_messages: Any,
        model_name: Optional[str] = None,
    ) -> str:
        """Chama o Gemini e devolve o texto da resposta.

        Percorre todas as chaves em rodízio e aplica backoff curto (503/timeout) ou
        espera adaptativa de até 60 s (429 / limite por minuto) quando todas falham.
        """
        effective_model = model_name or self._default_gemini_model

        def _call_one(api_key: str) -> str:
            llm = ChatGoogleGenerativeAI(
                google_api_key=api_key,
                model=effective_model,
                temperature=0.3,
                timeout=REQUEST_TIMEOUT_S,
                max_retries=0,  # quem retenta é o pool
            )
            return _message_text(llm.invoke(prompt_messages))

        return self._run_with_retries("gemini", "Gemini", self._gemini_keys, _call_one)


# ------------------------------------------------------- instância compartilhada
_pool: Optional[KeyPoolManager] = None
_pool_lock = threading.Lock()


def get_key_pool() -> KeyPoolManager:
    """Devolve o pool único do processo (criado na primeira chamada, thread-safe)."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = KeyPoolManager()
        return _pool
