"""Tela 3 (/Cadastro): o jogador, pelo celular, envia o apelido e o prompt de ataque.

É a página que o QR Code da Tela 2 abre. Depois do envio o jogador vai para a Tela 5.
"""

import streamlit as st

from core.models import MAX_PROMPT_CHARS, GamePhase
from core.security import MAX_USERNAME_CHARS, sanitize_username
from core.store import RegistrationClosedError, get_store

AVISO_TRANCADO = "🔒 As inscrições para esta rodada estão encerradas ou a partida já começou no telão!"

store = get_store()

# Já inscrito nesta rodada (mesma sessão, ou link com ?pid=): vai direto para a Tela 5.
pid = st.session_state.get("player_id") or st.query_params.get("pid")
if pid:
    if pid in store.players:
        st.session_state["player_id"] = pid
        st.switch_page("views/tela_5_largada.py")
    # Inscrição de uma rodada anterior: esquece e deixa se inscrever de novo.
    st.session_state.pop("player_id", None)
    if "pid" in st.query_params:
        del st.query_params["pid"]

st.title("🕵️ Teaming Arena")
st.markdown(
    "Convença o **Assistente Corporativo de MLOps** a revelar a **palavra-chave secreta**. "
    "Seu prompt vai passar por 3 guardrails: entrada, agente e DLP de saída."
)

if store.phase is not GamePhase.LOBBY:
    st.warning(AVISO_TRANCADO)

    @st.fragment(run_every="3s")
    def _aguardar_lobby() -> None:
        # Quem abriu o QR Code cedo (ou entre rodadas) recebe o formulário sozinho.
        if store.phase is GamePhase.LOBBY:
            st.rerun(scope="app")
        st.caption("Esta página se atualiza sozinha quando o apresentador abrir a próxima rodada.")

    _aguardar_lobby()
    st.stop()

with st.form("form_ataque"):
    username = st.text_input("Seu Nome / Apelido:", max_chars=MAX_USERNAME_CHARS)
    prompt = st.text_area(
        "Seu Prompt de Ataque (Tente descobrir a palavra-chave secreta!):",
        max_chars=MAX_PROMPT_CHARS,
        height=160,
    )
    enviar = st.form_submit_button(
        "🚀 Enviar Ataque e Aguardar Largada",
        type="primary",
        use_container_width=True,
    )

if enviar:
    nome = sanitize_username(username)  # pode virar "" (só espaços ou caracteres invisíveis)
    texto = (prompt or "").strip()
    if not nome or not texto:
        st.error("Preencha o seu nome e o seu prompt de ataque antes de enviar.")
    else:
        try:
            player = store.register_player(nome, texto)
        except RegistrationClosedError:
            # O Host clicou em PLAY entre a abertura do formulário e o envio.
            st.warning(AVISO_TRANCADO)
        else:
            st.session_state["player_id"] = player.player_id
            st.query_params["pid"] = player.player_id
            st.switch_page("views/tela_5_largada.py")
