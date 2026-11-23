"""Tela 1 (/INICIO, servida na raiz "/"): o Host define a palavra-chave secreta da rodada.

Defina a palavra ANTES de espelhar a tela no projetor. O campo fica mascarado por
segurança (o ícone de olho mostra o texto para conferir).
"""

import streamlit as st

from core.models import GamePhase
from core.security import validate_keyword_rules
from core.store import get_store

REGRAS = """
#### 📏 Regras para uma Boa Palavra-Chave
- Ter entre **4 e 30 caracteres**;
- Preferir uma **palavra única, código ou termo específico** (ex.: `ORACULO2026`, `PROJETO_FENIX`, `CANGUARETAMA`, `TURMALINA99`);
- **Evitar palavras comuns** do vocabulário de IA/programação (`python`, `modelo`, `segredo`, `chave`, `mlops`, `bom dia`) para não gerar falsos positivos.
"""

store = get_store()

st.markdown(
    "<h1 style='text-align: center;'>🔐 Teaming Arena — Configuração da Rodada (TELA 1)</h1>",
    unsafe_allow_html=True,
)

_, centro, _ = st.columns([1, 2, 1])
with centro:
    # Avisa antes de apagar uma rodada que já existe.
    phase, _, players = store.get_snapshot()
    if phase is GamePhase.LOBBY and players:
        st.warning(
            f"O lobby já está aberto com **{len(players)}** jogador(es) inscrito(s). "
            "Confirmar uma nova palavra-chave reinicia a rodada e apaga essas inscrições."
        )
        if st.button("↩️ Voltar ao Lobby sem trocar a palavra (Tela 2)"):
            st.switch_page("views/tela_2_lobby.py")
    elif phase is GamePhase.RUNNING:
        st.warning(
            "Há uma rodada **em andamento** no telão. Confirmar uma nova palavra-chave "
            "encerra essa rodada e apaga os resultados."
        )
        if st.button("📺 Voltar ao telão (Tela 4)"):
            st.switch_page("views/tela_4_jogo.py")
    elif phase is GamePhase.FINISHED:
        st.info("A rodada anterior terminou. Defina a palavra-chave da próxima rodada.")

    with st.form("form_palavra_chave"):
        keyword = st.text_input(
            "Palavra-Chave da Vez",
            type="password",
            max_chars=30,
            placeholder="Ex.: ORACULO2026",
            help="O texto fica oculto para ninguém ver no projetor. Use o ícone de olho para conferir.",
        )
        st.markdown(REGRAS)
        confirmar = st.form_submit_button(
            "Confirmar Palavra-Chave e Abrir Lobby ➡️",
            type="primary",
            use_container_width=True,
        )

    if confirmar:
        valida, mensagem = validate_keyword_rules(keyword)
        if valida:
            store.set_secret_and_open_lobby(keyword)
            st.switch_page("views/tela_2_lobby.py")
        else:
            st.error(mensagem)
