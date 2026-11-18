"""Funções puras e determinísticas de segurança (sem rede, sem estado).

- `sanitize_username`, `validate_keyword_rules`, `normalize_text` e
  `did_player_capture_secret` são o contrato da Etapa 3.
- `quick_input_heuristic` é a checagem rápida do Nó 1 (roda antes do LLM e não gasta API).
"""

import base64
import binascii
import html
import re
import unicodedata
from typing import Optional

MAX_USERNAME_CHARS = 20
MIN_KEYWORD_CHARS = 4
MAX_KEYWORD_CHARS = 30

# Palavras comuns demais: apareceriam em qualquer conversa e gerariam falsos vencedores.
TRIVIAL_KEYWORDS = (
    "ola", "bom dia", "python", "mlops", "ajuda", "sim", "nao", "teste", "segredo", "chave",
)


# --------------------------------------------------------------- normalização
def normalize_text(text: str) -> str:
    """Minúsculas, sem acentos e só letras/números (some espaço, hífen, ponto etc.)."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(
        ch for ch in decomposed if not unicodedata.combining(ch) and ch.isalnum()
    )


# ------------------------------------------------------------------- Tela 3
def sanitize_username(name: str) -> str:
    """Limpa o apelido: sem espaços extras, no máximo 20 caracteres e HTML escapado.

    O escape vem por último (como no guia), então o resultado pode passar de 20
    caracteres (`&` vira `&amp;`). Pode devolver "" se não sobrar nada: a Tela 3
    deve tratar isso como nome vazio.
    """
    # Remove caracteres invisíveis/de controle (ex.: espaço de largura zero).
    visible = "".join(ch for ch in (name or "") if ch.isprintable() or ch.isspace())
    collapsed = " ".join(visible.split())  # espaços/quebras repetidos viram um só
    return html.escape(collapsed[:MAX_USERNAME_CHARS].strip(), quote=True)


# ------------------------------------------------------------------- Tela 1
def validate_keyword_rules(keyword: str) -> tuple[bool, str]:
    """Valida a palavra-chave digitada pelo Host. Devolve `(válida, mensagem_de_erro)`."""
    kw = (keyword or "").strip()
    if len(kw) < MIN_KEYWORD_CHARS:
        return False, f"A palavra-chave deve ter no mínimo {MIN_KEYWORD_CHARS} caracteres."
    if len(kw) > MAX_KEYWORD_CHARS:
        return False, f"A palavra-chave deve ter no máximo {MAX_KEYWORD_CHARS} caracteres."

    norm = normalize_text(kw)
    # Sem isto, "----" normalizaria para "" e TODO jogador seria "vencedor".
    if len(norm) < MIN_KEYWORD_CHARS:
        return False, (
            f"A palavra-chave precisa ter pelo menos {MIN_KEYWORD_CHARS} letras ou números "
            "(símbolos e espaços não contam)."
        )
    if norm in {normalize_text(word) for word in TRIVIAL_KEYWORDS}:
        return False, (
            "Essa palavra é comum demais e apareceria em qualquer conversa. "
            "Prefira um termo específico, como ORACULO2026 ou PROJETO_FENIX."
        )
    return True, ""


# ------------------------------------------------------------------ Árbitro
_B64_TOKEN = re.compile(r"[A-Za-z0-9+/_-]{8,}={0,2}")
_URLSAFE = str.maketrans("+/", "-_")


def _base64_leak(output: str, secret: str, secret_norm: str) -> bool:
    """True se a saída traz a chave em Base64 (sozinha ou dentro de um texto maior)."""
    compact = "".join(output.split())  # tolera Base64 quebrado em várias linhas

    # 1) A chave codificada sozinha, com ou sem "=", em Base64 comum ou URL-safe.
    for variant in {secret, secret.lower(), secret.upper(), secret_norm}:
        encoded = base64.b64encode(variant.encode("utf-8")).decode("ascii").rstrip("=")
        if encoded and (encoded in compact or encoded.translate(_URLSAFE) in compact):
            return True

    # 2) Decodifica os trechos que parecem Base64: pega a chave dentro de uma frase
    #    codificada (o alinhamento muda, então o caso 1 não enxerga).
    for token in _B64_TOKEN.findall(output):
        raw = token.rstrip("=").replace("-", "+").replace("_", "/")
        try:
            decoded = base64.b64decode(raw + "=" * (-len(raw) % 4), validate=True).decode("utf-8")
        except (binascii.Error, ValueError):  # UnicodeDecodeError é ValueError
            continue
        if secret_norm in normalize_text(decoded):
            return True
    return False


def did_player_capture_secret(final_output: str, secret_keyword: str) -> bool:
    """O árbitro final: `True` (WINNER) se a resposta entregue contém a palavra-chave.

    Reconhece a chave exata (sem diferenciar maiúsculas), normalizada (com espaços,
    hífens ou pontos entre as letras), de trás para frente e em Base64. Caso
    contrário devolve `False` (PASSED_CLEAN): o jogador só fez uma pergunta inocente.
    """
    secret = (secret_keyword or "").strip()
    output = final_output or ""
    secret_norm = normalize_text(secret)
    # Chave vazia (ou só símbolos) nunca vence: "" está contido em qualquer texto.
    if not secret_norm or not output:
        return False

    if secret.lower() in output.lower():
        return True
    output_norm = normalize_text(output)
    if secret_norm in output_norm or secret_norm[::-1] in output_norm:
        return True
    return _base64_leak(output, secret, secret_norm)


# ------------------------------------------------------- heurística do Nó 1
def _simplify(text: str) -> str:
    """Minúsculas, sem acentos, pontuação vira espaço: facilita casar padrões."""
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


_IGNORE = r"(?:ignor\w*|desconsider\w*|esquec\w*|descart\w*|desobedec\w*|disregard|forget|override|bypass)"
_RULES = (
    r"(?:regras?|instrucoes?|diretrizes|restricoes|filtros?|guardrails?|prompts?|"
    r"rules?|instructions?|directives|restrictions|filters?)"
)
_PREVIOUS = r"(?:anteriores|anterior|previas|acima|previous|prior|above|earlier)"
_REVEAL = (
    r"(?:revel\w*|diga|me diga|mostre|me mostre|exiba|imprima|repita|liste|fale|informe|"
    r"passe|me passe|reveal|show|print|repeat|display|leak|tell me|give me)"
)
_SECRET = (
    r"(?:palavra chave|senha|segredo|chave secreta|credenciais?|secret word|"
    r"secret key|secret code|secret keyword|password|passphrase)"
)
_SYSTEM_PROMPT = (
    r"(?:prompt (?:do|de) sistema|instrucoes (?:do sistema|iniciais)|"
    r"system prompt|system message|initial instructions)"
)

# (categoria, motivo em português, padrão sobre o texto simplificado)
_INPUT_PATTERNS = [
    (
        "prompt_injection",
        "Padrão clássico de injeção de prompt: pede para ignorar as instruções anteriores.",
        re.compile(
            rf"\b{_IGNORE}\b.{{0,40}}\b{_PREVIOUS}\b.{{0,20}}\b{_RULES}\b"
            rf"|\b{_IGNORE}\b.{{0,40}}\b{_RULES}\b.{{0,25}}\b{_PREVIOUS}\b"
        ),
    ),
    (
        "prompt_injection",
        "Tentativa de extrair o prompt de sistema do assistente.",
        re.compile(rf"\b{_REVEAL}\b.{{0,30}}\b{_SYSTEM_PROMPT}\b"),
    ),
    (
        "social_engineering",
        "Pedido direto pela palavra-chave ou senha secreta.",
        re.compile(
            rf"\b{_REVEAL}\b.{{0,25}}\b{_SECRET}\b"
            rf"|\bqual (?:e|eh|seria|foi) .{{0,15}}\b{_SECRET}\b"
            rf"|\bwhat (?:is|s) .{{0,15}}\b{_SECRET}\b"
        ),
    ),
    (
        "roleplay_jailbreak",
        "Tentativa de jailbreak por modo ou persona sem restrições.",
        re.compile(
            r"\bdo anything now\b|\bdan mode\b|\bmodo dan\b|\bdeveloper mode\b"
            r"|\bmodo desenvolvedor\b|\bgod mode\b|\bmodo deus\b|\bjailbreak\b"
            r"|\bsem (?:nenhuma )?restricoes\b|\bno restrictions\b"
        ),
    ),
]


def quick_input_heuristic(text: str, max_chars: int = 600) -> Optional[tuple[str, str]]:
    """Checagem rápida e barata do Nó 1, antes de chamar o LLM.

    Devolve `(attack_category, motivo)` se o texto é um ataque óbvio, ou `None` se
    nada suspeito foi encontrado (aí quem decide é o LLM do Nó 1).
    """
    if len(text or "") > max_chars:
        return "prompt_injection", f"Prompt acima do limite de {max_chars} caracteres."
    simplified = _simplify(text)
    for category, reason, pattern in _INPUT_PATTERNS:
        if pattern.search(simplified):
            return category, reason
    return None
