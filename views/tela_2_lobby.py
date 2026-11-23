"""Tela 2 (/Lobby): QR Code para os celulares, inscritos ao vivo e o botão PLAY.

A palavra-chave NUNCA aparece nesta tela (ela vai para o projetor).
"""

import html
import io
import socket
from typing import Optional

import qrcode
import streamlit as st

from core.models import GamePhase, PlayerRecord
from core.runner import start_round_execution
from core.store import get_store

store = get_store()

# Sem palavra-chave definida não há lobby: volta para a Tela 1.
if store.phase is GamePhase.SETUP:
    st.switch_page("views/tela_1_inicio.py")

FASE_RENDERIZADA = store.phase

BADGES_CSS = """
<style>
.arena-badges { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.5rem 0 1rem 0; }
.arena-badge {
  padding: 0.35rem 0.8rem; border-radius: 999px; font-weight: 600; font-size: 1.05rem;
  background: rgba(33, 150, 243, 0.12); border: 1px solid rgba(33, 150, 243, 0.55);
}
</style>
"""


# ------------------------------------------------------------------ helpers
def _link_padrao() -> str:
    """Monta https://{host}/Cadastro a partir do cabeçalho Host da requisição."""
    headers = st.context.headers
    host = headers.get("Host") or "localhost:8501"
    local = host.split(":")[0] in ("localhost", "127.0.0.1", "0.0.0.0")
    proto = (headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
    scheme = proto or ("http" if local else "https")
    return f"{scheme}://{host}/Cadastro"


def _ip_na_rede_local() -> Optional[str]:
    """IP desta máquina na rede local (o UDP 'connect' não envia nenhum pacote)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


@st.cache_data(show_spinner=False)
def _qr_png(link: str) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def _nome_seguro(nome: str) -> str:
    """Escapa o nome para HTML, esteja ele já escapado (sanitize_username) ou não."""
    return html.escape(html.unescape(nome))


def _badges(players: list[PlayerRecord]) -> str:
    itens = "".join(f"<span class='arena-badge'>✅ {_nome_seguro(p.username)}</span>" for p in players)
    return f"<div class='arena-badges'>{itens}</div>"


@st.fragment(run_every="2s")
def _painel_inscritos() -> None:
    """Atualiza a cada 2 s, sem recarregar a página inteira (o QR Code fica parado)."""
    phase, _, players = store.get_snapshot()  # a palavra secreta é ignorada aqui
    if phase is not FASE_RENDERIZADA:
        st.rerun(scope="app")  # a fase mudou (Play em outra aba, reset...): redesenha a tela
    st.metric("Jogadores Prontos na Arena", len(players))
    if players:
        st.markdown(_badges(players), unsafe_allow_html=True)
    else:
        st.caption("⏳ Aguardando as primeiras inscrições...")


# -------------------------------------------------------------------- tela
st.markdown(BADGES_CSS, unsafe_allow_html=True)
st.markdown(
    "<h1 style='text-align: center;'>🎯 Teaming Arena — Lobby (TELA 2)</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='text-align: center; font-size: 1.15rem;'>Escaneie o QR Code, escolha um apelido e "
    "envie o seu prompt de ataque. A palavra-chave secreta já foi definida 🤫</p>",
    unsafe_allow_html=True,
)

esquerda, direita = st.columns(2, gap="large")

with esquerda:
    st.subheader("📲 Entre pelo celular")
    link = st.text_input(
        "Link da Sessão (editável se necessário):",
        value=_link_padrao(),
        key="lobby_link_sessao",
    ).strip()
    if not link:
        link = _link_padrao()
        st.warning("O link estava vazio; voltei para o endereço detectado automaticamente.")
    st.image(_qr_png(link), width=380)
    st.markdown(f"🔗 [{link}]({link})")
    st.code(link, language=None)
    host = link.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        ip = _ip_na_rede_local()
        sugestao = f"`{link.replace(host, ip, 1)}`" if ip else "`http://<IP-deste-computador>:8501/Cadastro`"
        st.caption(
            f"⚠️ Os celulares não conseguem abrir *{host}*. Para testar na rede local (mesmo Wi-Fi), "
            f"edite o link acima para {sugestao}."
        )

with direita:
    st.subheader("👥 Inscritos ao vivo")
    _painel_inscritos()

    if FASE_RENDERIZADA is GamePhase.LOBBY:
        if st.button(
            "▶️ PLAY — Trancar Envios e Iniciar Ataques!",
            type="primary",
            use_container_width=True,
        ):
            # Avisos em toast (somem sozinhos): um st.warning ficaria preso na tela mesmo
            # depois que o contador ao vivo já mostrasse jogadores inscritos.
            if not store.players:
                st.toast("Ainda não há jogadores inscritos. Aguarde pelo menos 1 inscrição para dar o PLAY.", icon="⏳")
            elif start_round_execution() or store.phase in (GamePhase.RUNNING, GamePhase.FINISHED):
                # Iniciou agora, ou já tinha sido iniciada (ex.: clique em outra aba).
                st.switch_page("views/tela_4_jogo.py")
            else:
                st.toast("Não foi possível iniciar a rodada. Atualize a página e tente de novo.", icon="⚠️")
    else:
        st.info("🔒 A rodada já começou: as inscrições estão trancadas.")
        if st.button("📺 Ir para o telão (Tela 4)", type="primary", use_container_width=True):
            st.switch_page("views/tela_4_jogo.py")

st.divider()
if st.button("⬅️ Trocar a palavra-chave (Tela 1)"):
    st.switch_page("views/tela_1_inicio.py")
