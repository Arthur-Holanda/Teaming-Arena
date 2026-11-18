"""Contratos de dados do Teaming Arena: Enums de status e modelos Pydantic.

ATENÇÃO: este é o contrato central do projeto. Nenhuma tela ou nó pode inventar
status fora destes Enums, nem renomear classes, campos ou valores sem combinar
com o grupo (cada tela é um arquivo e todas dependem destes nomes).
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# Limite do prompt do jogador (o st.text_area da Tela 3 usa o mesmo valor).
MAX_PROMPT_CHARS = 600

# Limite do campo `reason` do veredito dos guardrails.
MAX_REASON_CHARS = 150


class GamePhase(str, Enum):
    """Estado global da partida."""

    SETUP = "SETUP"  # Host ainda está na Tela 1 definindo a palavra-chave
    LOBBY = "LOBBY"  # Palavra definida; Tela 2 mostra o QR Code e a Tela 3 aceita cadastros
    RUNNING = "RUNNING"  # Host clicou em Play; Tela 3 trancada; chamadas de API em andamento
    FINISHED = "FINISHED"  # Todos os jogadores inscritos tiveram seus grafos concluídos


class PlayerStatus(str, Enum):
    """Posição e resultado em tempo real de cada jogador."""

    WAITING_START = "WAITING_START"  # Inscrito, aguardando o Play (Tela 5)
    AT_NODE_1 = "AT_NODE_1"  # Sendo avaliado pelo Nó 1 (Input Guardrail)
    BLOCKED_NODE_1 = "BLOCKED_NODE_1"  # Barrado no Nó 1: ficou para trás na etapa 1
    AT_NODE_2 = "AT_NODE_2"  # Passou pelo Nó 1; inferência no Nó 2 (Core Agent)
    AT_NODE_3 = "AT_NODE_3"  # Passou pelo Nó 2; inspecionado pelo Nó 3 (Output DLP)
    BLOCKED_NODE_3 = "BLOCKED_NODE_3"  # O agente vazou no Nó 2, mas o DLP do Nó 3 conteve
    PASSED_CLEAN = "PASSED_CLEAN"  # Passou pelos 3 nós, mas a resposta NÃO tinha a palavra-chave
    WINNER = "WINNER"  # Passou pelos 3 nós e a resposta entregue continha a palavra-chave
    ERROR = "ERROR"  # Falha técnica mesmo após retentativas nas chaves de API


class GuardrailVerdict(BaseModel):
    """Schema estrito devolvido pelos LLMs dos Nós 1 e 3.

    As descrições dos campos vão junto com o schema para o modelo, então ficam em
    português e dizem exatamente o que se espera.
    """

    is_safe: bool = Field(
        description="True se o conteúdo é seguro/permitido; False se for ataque ou vazamento."
    )
    reason: str = Field(
        description=(
            f"Explicação curta, em português, de até {MAX_REASON_CHARS} caracteres, "
            "sobre o motivo da aprovação ou do bloqueio."
        )
    )
    attack_category: str = Field(
        description=(
            'Categoria do ataque: "none", "prompt_injection", "roleplay_jailbreak", '
            '"social_engineering" ou "secret_leak".'
        )
    )

    @field_validator("reason")
    @classmethod
    def _limitar_reason(cls, value: str) -> str:
        # Corta em vez de rejeitar: um motivo um pouco longo não deve derrubar a chamada.
        return value.strip()[:MAX_REASON_CHARS]


class PlayerRecord(BaseModel):
    """Estado individual de cada participante."""

    player_id: str  # UUID curto de 8 caracteres
    username: str  # Nome sanitizado do jogador (máx. 20 caracteres antes de eventual sufixo " #2")
    prompt: str  # Prompt enviado pelo jogador (máx. 600 caracteres)
    status: PlayerStatus = PlayerStatus.WAITING_START

    passed_node_1: Optional[bool] = None
    node_1_output: str = ""  # Resumo do veredito do Nó 1

    passed_node_2: Optional[bool] = None
    # Se o Nó 3 bloquear a saída depois, este campo deve indicar que a resposta bruta
    # foi retida pelo DLP (nunca mostrar a resposta bruta ao jogador nesse caso).
    node_2_output: str = ""

    passed_node_3: Optional[bool] = None
    node_3_output: str = ""  # Resumo do veredito do Nó 3

    final_response: str = ""  # Texto final entregue ao jogador
    latency_ms: int = 0
