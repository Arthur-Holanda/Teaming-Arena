"""Estado global do Teaming Arena (singleton thread-safe).

Todas as telas (Streamlit) e todas as threads do grafo leem e escrevem aqui.
Acesso padrão, em qualquer arquivo:

    from core.store import get_store

    store = get_store()
    phase, secret, players = store.get_snapshot()   # leitura segura para renderizar
    store.update_player(player_id, status=PlayerStatus.AT_NODE_2)

Dentro de threads (ThreadPoolExecutor do runner) prefira receber o `store` por
argumento em vez de chamar `get_store()` lá dentro.
"""

import threading
import uuid
from typing import Any

import streamlit as st

from core.models import MAX_PROMPT_CHARS, GamePhase, PlayerRecord


class RegistrationClosedError(RuntimeError):
    """`register_player` foi chamado fora da fase LOBBY (inscrições fechadas).

    A Tela 3 deve capturar este erro e mostrar o aviso de "inscrições encerradas",
    pois o Host pode clicar em Play entre a abertura do formulário e o envio.
    """


class ArenaStore:
    """Estado da partida, protegido por um RLock (`self.lock`).

    Os atributos `phase`, `secret_keyword` e `players` são propriedades que sempre
    passam pelo lock; `players` devolve uma cópia (para alterar um jogador, use
    `update_player`). Para operações com vários passos (ex.: verificar a fase e
    depois mudá-la), envolva tudo em `with store.lock:` — o lock é reentrante.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._phase: GamePhase = GamePhase.SETUP
        self._secret_keyword: str = ""
        self._players: dict[str, PlayerRecord] = {}

    # ------------------------------------------------------------ atributos
    @property
    def phase(self) -> GamePhase:
        with self.lock:
            return self._phase

    @phase.setter
    def phase(self, value: GamePhase) -> None:
        with self.lock:
            self._phase = GamePhase(value)  # rejeita valores fora do Enum

    @property
    def secret_keyword(self) -> str:
        """Somente leitura. Para definir, use `set_secret_and_open_lobby`."""
        with self.lock:
            return self._secret_keyword

    @property
    def players(self) -> dict[str, PlayerRecord]:
        """Cópia do dicionário `player_id -> PlayerRecord` (alterar a cópia não muda o estado)."""
        with self.lock:
            return {pid: p.model_copy() for pid, p in self._players.items()}

    # ------------------------------------------------------------- métodos
    def set_secret_and_open_lobby(self, keyword: str) -> None:
        """Define a palavra-chave, limpa jogadores de rodadas anteriores e abre o LOBBY."""
        keyword = (keyword or "").strip()
        if not keyword:
            raise ValueError("A palavra-chave não pode ser vazia.")
        with self.lock:
            self._secret_keyword = keyword
            self._players = {}
            self._phase = GamePhase.LOBBY

    def register_player(self, username: str, prompt: str) -> PlayerRecord:
        """Inscreve um jogador (só na fase LOBBY) e devolve uma cópia do seu registro.

        Nomes repetidos recebem sufixo automático ("Arthur", "Arthur #2", "Arthur #3"...).
        O `username` deve chegar já sanitizado (`core.security.sanitize_username`).

        Raises:
            RegistrationClosedError: a fase atual não é LOBBY.
            ValueError: `username` ou `prompt` vazios.
        """
        username = (username or "").strip()
        prompt = (prompt or "").strip()
        if not username:
            raise ValueError("O nome de usuário não pode ser vazio.")
        if not prompt:
            raise ValueError("O prompt não pode ser vazio.")

        with self.lock:
            if self._phase != GamePhase.LOBBY:
                raise RegistrationClosedError(
                    f"Inscrições fechadas (fase atual: {self._phase.value})."
                )
            taken = {p.username for p in self._players.values()}
            unique_name, n = username, 2
            while unique_name in taken:
                unique_name = f"{username} #{n}"
                n += 1

            player_id = uuid.uuid4().hex[:8]
            while player_id in self._players:
                player_id = uuid.uuid4().hex[:8]

            record = PlayerRecord(
                player_id=player_id,
                username=unique_name,
                prompt=prompt[:MAX_PROMPT_CHARS],
            )
            self._players[player_id] = record
            return record.model_copy()

    def update_player(self, player_id: str, **kwargs: Any) -> bool:
        """Atualiza campos de um jogador em tempo real (usado pelos nós do grafo).

        A atualização é atômica e validada: se qualquer valor for inválido (ex.: um
        `status` fora do Enum), nada é alterado. Devolve False, sem erro, se o jogador
        não existe mais (ex.: o Host reiniciou a partida com threads ainda rodando).

        Raises:
            ValueError: algum nome em `kwargs` não é campo de `PlayerRecord`.
            pydantic.ValidationError: algum valor tem tipo inválido.
        """
        unknown = set(kwargs) - set(PlayerRecord.model_fields)
        if unknown:
            raise ValueError(f"Campos desconhecidos em update_player: {sorted(unknown)}")

        with self.lock:
            current = self._players.get(player_id)
            if current is None:
                return False
            data = current.model_dump()
            data.update(kwargs)
            self._players[player_id] = PlayerRecord.model_validate(data)
            return True

    def get_snapshot(self) -> tuple[GamePhase, str, list[PlayerRecord]]:
        """Cópia segura do estado para renderizar as telas.

        Devolve `(fase, palavra_secreta, jogadores_na_ordem_de_inscricao)`. Atenção:
        a palavra secreta vem junto; as telas do Host/jogadores nunca devem exibi-la
        antes do fim da rodada.
        """
        with self.lock:
            # Todos os campos de PlayerRecord são imutáveis (str/int/bool/Enum),
            # então uma cópia rasa por jogador já isola o estado interno.
            return (
                self._phase,
                self._secret_keyword,
                [p.model_copy() for p in self._players.values()],
            )

    def reset_to_setup(self) -> None:
        """Volta tudo para SETUP (nova partida na Tela 1)."""
        with self.lock:
            self._phase = GamePhase.SETUP
            self._secret_keyword = ""
            self._players = {}


@st.cache_resource(show_spinner=False)
def get_store() -> ArenaStore:
    """Singleton global: a mesma instância para todas as sessões e threads do processo."""
    return ArenaStore()
