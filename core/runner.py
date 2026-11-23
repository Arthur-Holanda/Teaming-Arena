"""Motor de disparo concorrente: processa todos os jogadores quando o Host clica em Play.

Uso (Tela 2, ao clicar em PLAY):

    from core.runner import start_round_execution

    if start_round_execution():
        st.switch_page("views/tela_4_jogo.py")

`start_round_execution()` volta na hora; o processamento roda em threads de segundo plano
e cada nó atualiza o `ArenaStore`, que as Telas 4 e 5 leem.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from core import graph
from core.models import GamePhase, PlayerStatus
from core.store import ArenaStore, get_store

logger = logging.getLogger(__name__)

# Jogadores processados ao mesmo tempo.
MAX_WORKERS = 4

# Pausa (s) depois de cada nó mostrar o seu status. O telão consegue enxergar cada nome
# descendo de nó em nó, e as chamadas às APIs ficam espalhadas (menos erros 429).
NODE_PAUSE_SECONDS = 0.8

# Status finais: depois de um destes o jogador não muda mais.
_TERMINAL_STATUSES = frozenset(
    {
        PlayerStatus.BLOCKED_NODE_1,
        PlayerStatus.BLOCKED_NODE_3,
        PlayerStatus.PASSED_CLEAN,
        PlayerStatus.WINNER,
        PlayerStatus.ERROR,
    }
)


def start_round_execution() -> bool:
    """Tranca as inscrições (fase RUNNING) e dispara o processamento em segundo plano.

    Só funciona na fase LOBBY e com pelo menos 1 jogador. Devolve `True` se a rodada
    começou, `False` se não fez nada (outra rodada já está em andamento, ou não há
    jogadores). O Play clicado duas vezes não dispara duas rodadas.
    """
    store = get_store()
    with store.lock:  # checar a fase e mudá-la tem de ser um passo só
        if store.phase != GamePhase.LOBBY:
            logger.warning("Play ignorado: fase atual é %s (esperado LOBBY).", store.phase.value)
            return False
        player_ids = list(store.players)  # na ordem de inscrição
        if not player_ids:
            logger.warning("Play ignorado: não há jogadores inscritos.")
            return False
        store.phase = GamePhase.RUNNING  # trava imediatamente novos envios na Tela 3

        try:
            threading.Thread(
                target=_run_batch, args=(store, player_ids), name="arena-batch", daemon=True
            ).start()
        except Exception:
            store.phase = GamePhase.LOBBY  # não deixa a partida presa em RUNNING sem ninguém rodando
            raise
    logger.info("Rodada iniciada com %d jogador(es).", len(player_ids))
    return True


def _run_batch(store: ArenaStore, player_ids: list[str]) -> None:
    """Thread mestra: processa a fila com um pool de threads e, no fim, encerra a rodada."""
    graph.NODE_PAUSE_SECONDS = NODE_PAUSE_SECONDS
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="arena-player") as pool:
            list(pool.map(lambda player_id: _process_player(store, player_id), player_ids))
    except Exception:  # noqa: BLE001
        logger.exception("Erro inesperado no processamento da rodada.")
    finally:
        _finish_round(store, player_ids)


def _process_player(store: ArenaStore, player_id: str) -> None:
    """Roda o grafo de UM jogador e registra quanto tempo levou."""
    started = time.monotonic()
    try:
        graph.run_player_graph(player_id)  # nunca levanta: falhas viram status ERROR
    except Exception:  # noqa: BLE001 - garantia extra: uma thread ruim não derruba as outras
        logger.exception("Erro inesperado ao processar o jogador %s.", player_id)
        store.update_player(
            player_id, status=PlayerStatus.ERROR, final_response=graph.TECHNICAL_ERROR_MESSAGE
        )
    # Tempo total do jogador na arena, já com as pausas visuais de cada nó.
    store.update_player(player_id, latency_ms=int((time.monotonic() - started) * 1000))


def _finish_round(store: ArenaStore, player_ids: list[str]) -> None:
    """Marca a rodada como FINISHED, mas só se ela ainda for a mesma que foi disparada."""
    with store.lock:
        current = store.players
        # Se o Host reiniciou a partida enquanto as threads rodavam, a fase já não é RUNNING
        # ou os jogadores são outros (nova rodada): não se mexe no estado dessa nova partida.
        if store.phase != GamePhase.RUNNING or set(current) != set(player_ids):
            logger.info("Rodada encerrada sem alterar a fase: a partida foi reiniciada.")
            return
        # FINISHED significa "todos os grafos concluídos": ninguém pode ficar pelo meio.
        for player_id, player in current.items():
            if player.status not in _TERMINAL_STATUSES:
                logger.error("Jogador %s ficou em %s; marcando ERROR.", player_id, player.status.value)
                store.update_player(
                    player_id,
                    status=PlayerStatus.ERROR,
                    final_response=graph.TECHNICAL_ERROR_MESSAGE,
                )
        store.phase = GamePhase.FINISHED
    logger.info("Rodada finalizada.")
