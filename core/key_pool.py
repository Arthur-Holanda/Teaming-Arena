"""Pool de chaves de API (Groq e Gemini) com rodízio e fallback automático.

Uso típico (nos nós do grafo, Etapa 3):

    from core.key_pool import get_key_pool

    pool = get_key_pool()
    verdict = pool.invoke_groq_structured(messages, GuardrailVerdict)  # Nós 1 e 3
    texto = pool.invoke_gemini_chat(messages)                          # Nó 2

Use sempre ``get_key_pool()`` em vez de instanciar ``KeyPoolManager()`` direto:
o rodízio só distribui a carga se todas as threads compartilharem o mesmo pool.

As chaves são lidas, nesta ordem, de ``os.environ`` (que recebe o conteúdo do
``.env`` via ``load_dotenv()``) e de ``st.secrets`` (Streamlit Community Cloud).
"""

from __future__ import annotations

import itertools
import logging
import os
import threading
from typing import Any, Optional, Sequence

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from pydantic import BaseModel

logger = logging.getLogger(__name__)

GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"

# De 1 até 3 chaves gratuitas por provedor (GROQ_API_KEY_1..3 / GEMINI_API_KEY_1..3).
MAX_KEYS_PER_PROVIDER = 3

# Tempo máximo (s) de cada chamada. Se estourar, o pool passa para a próxima chave.
REQUEST_TIMEOUT_S = 40


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


class KeyPoolManager:
    """Rodízio thread-safe (round-robin) de chaves, com fallback automático."""

    def __init__(self) -> None:
        load_dotenv()  # não sobrescreve variáveis já definidas no ambiente
        self._groq_keys = _collect_keys("GROQ_API_KEY", ("GROQ_API_KEY",))
        self._gemini_keys = _collect_keys("GEMINI_API_KEY", ("GOOGLE_API_KEY",))
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

    # --------------------------------------------------------------- rodízio
    def _attempt_order(self, provider: str) -> list[int]:
        """Índices das chaves na ordem de tentativa: começa na próxima do rodízio.

        Cada chave aparece uma única vez, então o fallback percorre o pool inteiro
        sem repetir chave, mesmo com várias threads sorteando ao mesmo tempo.
        """
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

    def _record_failure(
        self, label: str, position: int, total: int, exc: Exception, errors: list[str]
    ) -> None:
        detail = self._scrub(f"{type(exc).__name__}: {exc}")[:200]
        errors.append(f"chave #{position}: {detail}")
        if position < total:
            logger.warning(
                "%s: chave #%d/%d falhou (%s); tentando a próxima.",
                label, position, total, type(exc).__name__,
            )

    # ----------------------------------------------------------------- Groq
    def invoke_groq_structured(
        self,
        prompt_messages: Any,
        pydantic_schema: type[BaseModel],
        model_name: str = GROQ_DEFAULT_MODEL,
    ) -> BaseModel:
        """Chama a Groq pedindo saída estruturada no schema Pydantic informado.

        Em caso de rate limit (429), falha de rede ou de parseamento, tenta
        imediatamente a próxima chave do pool, até esgotar todas.
        Devolve uma instância de ``pydantic_schema``.
        """
        order = self._attempt_order("groq")
        errors: list[str] = []
        for position, idx in enumerate(order, start=1):
            try:
                llm = ChatGroq(
                    api_key=self._groq_keys[idx],
                    model=model_name,
                    temperature=0.0,
                    timeout=REQUEST_TIMEOUT_S,
                    max_retries=0,  # quem retenta é o pool, com outra chave
                )
                result = llm.with_structured_output(pydantic_schema).invoke(prompt_messages)
                if result is None:
                    raise ValueError("a Groq devolveu uma resposta estruturada vazia")
                return result
            except Exception as exc:
                self._record_failure("Groq", position, len(order), exc, errors)
        raise KeyPoolError(
            f"Todas as {len(order)} chave(s) Groq falharam. " + " | ".join(errors)
        )

    # --------------------------------------------------------------- Gemini
    def invoke_gemini_chat(
        self,
        prompt_messages: Any,
        model_name: str = GEMINI_DEFAULT_MODEL,
    ) -> str:
        """Chama o Gemini e devolve o texto da resposta.

        Em caso de rate limit (429), timeout ou falha de rede, tenta
        automaticamente a próxima chave do pool, até esgotar todas.
        """
        order = self._attempt_order("gemini")
        errors: list[str] = []
        for position, idx in enumerate(order, start=1):
            try:
                llm = ChatGoogleGenerativeAI(
                    google_api_key=self._gemini_keys[idx],
                    model=model_name,
                    temperature=0.3,
                    timeout=REQUEST_TIMEOUT_S,
                    max_retries=0,  # quem retenta é o pool, com outra chave
                )
                return _message_text(llm.invoke(prompt_messages))
            except Exception as exc:
                self._record_failure("Gemini", position, len(order), exc, errors)
        raise KeyPoolError(
            f"Todas as {len(order)} chave(s) Gemini falharam. " + " | ".join(errors)
        )


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
