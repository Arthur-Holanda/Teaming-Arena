"""Tela 5 (/Largada): o jogador acompanha, no celular, o próprio prompt passando pelos 3 nós.

O id do jogador fica na sessão e no endereço (?pid=...): atualizar a página não perde nada.
A palavra-chave do store nunca é exibida aqui; o jogador só a vê se ela vier na própria
resposta que o DLP liberou (ou seja, se ele venceu).
"""

import html

import streamlit as st

from core.models import GamePhase, PlayerRecord, PlayerStatus
from core.store import get_store

S = PlayerStatus

VEREDITOS = {
    S.BLOCKED_NODE_1: "Seu prompt foi barrado logo na entrada, pelo **Nó 1 (Input Guardrail)**.",
    S.BLOCKED_NODE_3: (
        "O agente quase vazou a chave, mas o **DLP do Nó 3** interceptou a resposta antes de ela chegar até você."
    ),
    S.PASSED_CLEAN: (
        "Seu prompt passou pelos 3 guardrails, mas a resposta **não continha a palavra-chave**."
    ),
    S.ERROR: "Houve uma **falha técnica** ao processar o seu prompt (as APIs não responderam).",
}

store = get_store()

pid = st.session_state.get("player_id") or st.query_params.get("pid")
player = store.players.get(pid) if pid else None

if player is None:
    st.session_state.pop("player_id", None)
    st.title("🕵️ Teaming Arena")
    st.info(
        "Não encontramos a sua inscrição nesta rodada. "
        "Ela pode ter terminado ou sido reiniciada pelo apresentador."
    )
    if st.button("📝 Ir para o cadastro", type="primary", use_container_width=True):
        st.switch_page("views/tela_3_cadastro.py")
    st.stop()

# Guarda o id na sessão e no endereço (st.switch_page não leva os parâmetros da URL junto).
st.session_state["player_id"] = pid
if st.query_params.get("pid") != pid:
    st.query_params["pid"] = pid

st.title(f"👤 {html.unescape(player.username)}")
st.caption("Acompanhe o seu ataque passando pelos guardrails, em tempo real.")
with st.expander("📝 Seu prompt de ataque", expanded=False):
    st.text(player.prompt)


# ------------------------------------------------------------------ nós
def _no_1(p: PlayerRecord) -> None:
    with st.container(border=True):
        st.markdown("**Etapa 1 — Nó 1 (Input Guardrail)**")
        if p.status is S.AT_NODE_1:
            st.markdown("🔄 Analisando o seu prompt...")
        elif p.passed_node_1:
            st.markdown("✅ Aprovado pelo filtro de entrada")
        elif p.passed_node_1 is False:
            st.markdown("🛑 Bloqueado no Nó 1")
        else:
            st.markdown("⚠️ Não concluído (falha técnica)")
        if p.node_1_output:
            st.caption(p.node_1_output)


def _no_2(p: PlayerRecord) -> None:
    if not p.passed_node_1:
        return
    with st.container(border=True):
        st.markdown("**Etapa 2 — Nó 2 (Core Agent / O Cofre)**")
        if p.status is S.AT_NODE_2:
            st.markdown("🔄 O agente está gerando a resposta...")
        elif p.passed_node_2 and not p.node_2_output:
            st.markdown("✅ Resposta gerada. Aguardando a auditoria do DLP (Nó 3)...")
        elif p.passed_node_2:
            st.markdown("✅ Resposta gerada")
        else:
            st.markdown("⚠️ Não concluído (falha técnica)")
        if p.node_2_output:
            if p.status is S.BLOCKED_NODE_3:
                st.caption(p.node_2_output)  # "[Resposta retida pelo DLP...]"
            else:
                with st.expander("📄 Ver a saída do agente (Nó 2)"):
                    st.markdown(p.node_2_output)


def _no_3(p: PlayerRecord) -> None:
    if not p.passed_node_2:
        return
    with st.container(border=True):
        st.markdown("**Etapa 3 — Nó 3 (Output Guardrail / DLP)**")
        if p.status is S.AT_NODE_3:
            st.markdown("🔄 Auditando a resposta antes de entregá-la...")
        elif p.passed_node_3:
            st.markdown("✅ Liberada pelo DLP")
        elif p.passed_node_3 is False:
            st.markdown("🛑 Interceptada pelo DLP")
        else:
            st.markdown("⚠️ Não concluído (falha técnica)")
        if p.node_3_output:
            st.caption(p.node_3_output)
        if p.passed_node_3 and p.final_response:
            st.markdown("**Resposta final entregue a você:**")
            st.markdown(p.final_response)


def _veredito(p: PlayerRecord) -> None:
    if p.status is S.WINNER:
        chave = f"baloes_{p.player_id}"
        if not st.session_state.get(chave):  # balões uma única vez
            st.session_state[chave] = True
            st.balloons()
        st.success("🏆 **PARABÉNS!** Você enganou os Guardrails e capturou a palavra-chave!")
    elif p.status in VEREDITOS:
        alerta = st.error if p.status in (S.BLOCKED_NODE_1, S.BLOCKED_NODE_3) else st.warning
        alerta(f"🛑 **Tente de novo em outra rodada**\n\n{VEREDITOS[p.status]}")


@st.fragment(run_every="1.5s")
def _acompanhar() -> None:
    phase, _, players = store.get_snapshot()  # a palavra secreta é ignorada aqui
    p = next((x for x in players if x.player_id == pid), None)
    if p is None:
        st.rerun(scope="app")  # a partida foi reiniciada: a página mostra o aviso

    if p.status is S.WAITING_START:
        if phase is GamePhase.LOBBY:
            st.info("⏳ Prompt registrado com sucesso! Aguardando o apresentador clicar em PLAY na Tela 2...")
        else:
            st.info("🚦 A rodada começou! Seu prompt está na fila e logo entra no Nó 1...")
        return

    _veredito(p)
    _no_1(p)
    _no_2(p)
    _no_3(p)


_acompanhar()
