"""Tela 4 (/Jogo): telão de observabilidade em tempo real com o grafo vertical.

Exibe os 3 nós do pipeline Defense-in-Depth + a linha final de Vencedores, de cima para
baixo, com a identificação da etapa à esquerda e os badges dos participantes à direita.
A palavra-chave secreta nunca é exibida na tela principal (só pode ser revelada pelo
apresentador dentro do painel de inspeção, depois que a rodada termina).
"""

import html
import os

import streamlit as st

from core.models import GamePhase, PlayerRecord, PlayerStatus
from core.store import get_store

S = PlayerStatus


def _model_label(env_name: str, default: str) -> str:
    val = os.environ.get(env_name)
    if not (isinstance(val, str) and val.strip()):
        try:
            val = st.secrets.get(env_name)
        except Exception:
            val = None
    return val.strip() if isinstance(val, str) and val.strip() else default


GROQ_MODEL_LABEL = _model_label("GROQ_MODEL", "openai/gpt-oss-120b")
GEMINI_MODEL_LABEL = _model_label("GEMINI_MODEL", "gemini-3.6-flash")

TERMINAL_STATUSES = frozenset(
    {
        S.BLOCKED_NODE_1,
        S.BLOCKED_NODE_3,
        S.PASSED_CLEAN,
        S.WINNER,
        S.ERROR,
    }
)

STATUS_LABELS = {
    S.WAITING_START: "🚦 Na fila",
    S.AT_NODE_1: "⏳ No Nó 1 (Input)",
    S.BLOCKED_NODE_1: "🛑 Barrado no Nó 1",
    S.AT_NODE_2: "⚙️ No Nó 2 (Core Agent)",
    S.AT_NODE_3: "🔍 No Nó 3 (DLP)",
    S.BLOCKED_NODE_3: "⚠️ Barrado no DLP (Nó 3)",
    S.PASSED_CLEAN: "💬 Passou Limpo (Sem Vazamento)",
    S.WINNER: "🏆 Vencedor",
    S.ERROR: "❌ Erro técnico",
}

GRAPH_CSS = """
<style>
@keyframes arena-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.55); transform: scale(1); }
  50% { box-shadow: 0 0 0 7px rgba(59, 130, 246, 0); transform: scale(1.02); }
}
@keyframes arena-pulse-amber {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.55); transform: scale(1); }
  50% { box-shadow: 0 0 0 7px rgba(245, 158, 11, 0); transform: scale(1.02); }
}

.arena-graph {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin: 0.75rem 0 1.25rem 0;
}

.arena-queue-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  padding: 0.65rem 1rem;
  margin-bottom: 0.75rem;
  border-radius: 12px;
  border: 1px dashed rgba(148, 163, 184, 0.55);
  background: rgba(148, 163, 184, 0.08);
  font-size: 0.92rem;
}
.arena-queue-label {
  font-weight: 700;
  margin-right: 0.25rem;
  opacity: 0.9;
}

.arena-row {
  display: grid;
  grid-template-columns: minmax(210px, 30%) 72px minmax(0, 1fr);
  align-items: stretch;
  gap: 0.75rem;
}

.arena-node-info {
  border-radius: 14px;
  padding: 1rem 1.1rem;
  border: 1px solid rgba(148, 163, 184, 0.35);
  background: rgba(148, 163, 184, 0.08);
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}
.arena-node-info.arena-winner-card {
  border: 1.5px solid rgba(34, 197, 94, 0.65);
  background: rgba(34, 197, 94, 0.12);
}
.arena-step-tag {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  opacity: 0.72;
  margin-bottom: 0.2rem;
}
.arena-node-title {
  font-size: 1.15rem;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 0.25rem;
}
.arena-node-sub {
  font-size: 0.88rem;
  opacity: 0.82;
  line-height: 1.35;
}
.arena-node-sub code {
  font-size: 0.82rem;
  padding: 0.08rem 0.35rem;
  border-radius: 6px;
  background: rgba(148, 163, 184, 0.2);
}

.arena-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
}
.arena-node-icon {
  width: 52px;
  height: 52px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  border: 2px solid rgba(59, 130, 246, 0.65);
  background: rgba(59, 130, 246, 0.14);
  z-index: 1;
  flex-shrink: 0;
}
.arena-node-icon.arena-winner-icon {
  border-color: rgba(34, 197, 94, 0.85);
  background: rgba(34, 197, 94, 0.18);
}

.arena-connector-row {
  display: grid;
  grid-template-columns: minmax(210px, 30%) 72px minmax(0, 1fr);
  gap: 0.75rem;
  height: 30px;
}
.arena-connector-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.arena-arrow {
  font-size: 1.35rem;
  font-weight: 800;
  line-height: 1;
  color: rgba(59, 130, 246, 0.85);
}

.arena-players-box {
  border-radius: 14px;
  padding: 0.85rem 1rem;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(148, 163, 184, 0.05);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  align-content: center;
  gap: 0.45rem;
  min-height: 82px;
  min-width: 0;
}
.arena-players-box.arena-winner-box {
  border: 1.5px solid rgba(34, 197, 94, 0.55);
  background: rgba(34, 197, 94, 0.07);
}
.arena-empty {
  font-size: 0.92rem;
  opacity: 0.68;
  font-style: italic;
}

.arena-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.72rem;
  border-radius: 999px;
  font-size: 0.92rem;
  font-weight: 600;
  line-height: 1.25;
  max-width: 100%;
  word-break: break-word;
  border: 1px solid transparent;
}
.badge-queue {
  background: rgba(148, 163, 184, 0.16);
  border-color: rgba(148, 163, 184, 0.45);
  font-size: 0.84rem;
  padding: 0.2rem 0.6rem;
}
.badge-active-1 {
  background: rgba(59, 130, 246, 0.22);
  border-color: rgba(59, 130, 246, 0.85);
  animation: arena-pulse 1.35s infinite;
}
.badge-active-2 {
  background: rgba(245, 158, 11, 0.22);
  border-color: rgba(245, 158, 11, 0.85);
  animation: arena-pulse-amber 1.35s infinite;
}
.badge-active-3 {
  background: rgba(14, 165, 233, 0.22);
  border-color: rgba(14, 165, 233, 0.85);
  animation: arena-pulse 1.35s infinite;
}
.badge-passed {
  background: rgba(148, 163, 184, 0.1);
  border-color: rgba(148, 163, 184, 0.32);
  font-size: 0.8rem;
  font-weight: 500;
  padding: 0.18rem 0.55rem;
  opacity: 0.68;
}
.badge-blocked-1 {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(239, 68, 68, 0.78);
}
.badge-blocked-3 {
  background: rgba(249, 115, 22, 0.22);
  border-color: rgba(249, 115, 22, 0.82);
}
.badge-clean {
  background: rgba(100, 116, 139, 0.22);
  border-color: rgba(148, 163, 184, 0.65);
}
.badge-winner {
  background: rgba(34, 197, 94, 0.26);
  border: 2px solid rgba(34, 197, 94, 0.92);
  box-shadow: 0 0 14px rgba(34, 197, 94, 0.32);
  font-size: 1.08rem;
  font-weight: 700;
  padding: 0.45rem 0.95rem;
}
.badge-error {
  background: rgba(190, 24, 93, 0.2);
  border-color: rgba(244, 63, 94, 0.75);
}

@media (max-width: 820px) {
  .arena-row {
    grid-template-columns: 1fr;
  }
  .arena-center,
  .arena-connector-row {
    display: none;
  }
  .arena-graph {
    gap: 0.75rem;
  }
}
</style>
"""


# ------------------------------------------------------------------ helpers
def _nome_seguro(nome: str) -> str:
    """Escapa o nome para HTML, esteja ele já escapado (sanitize_username) ou não."""
    return html.escape(html.unescape(nome or ""), quote=True)


def _tooltip_seguro(texto: str) -> str:
    return html.escape(texto or "", quote=True)


def _error_node(p: PlayerRecord) -> int:
    """Identifica em qual nó (1, 2 ou 3) ocorreu uma falha técnica."""
    if p.passed_node_1 is None:
        return 1
    if p.passed_node_2 is None:
        return 2
    return 3


def _badge(label_html: str, css_class: str, tooltip: str = "") -> str:
    title_attr = f' title="{_tooltip_seguro(tooltip)}"' if tooltip else ""
    return f'<span class="arena-badge {css_class}"{title_attr}>{label_html}</span>'


def _compute_metrics(players: list[PlayerRecord]) -> dict[str, int]:
    blocked_1 = sum(1 for p in players if p.status is S.BLOCKED_NODE_1)
    blocked_3 = sum(1 for p in players if p.status is S.BLOCKED_NODE_3)
    passed_clean = sum(1 for p in players if p.status is S.PASSED_CLEAN)
    winners = sum(1 for p in players if p.status is S.WINNER)
    errors = sum(1 for p in players if p.status is S.ERROR)
    done = sum(1 for p in players if p.status in TERMINAL_STATUSES)
    return {
        "total": len(players),
        "blocked_1": blocked_1,
        "blocked_3": blocked_3,
        "passed_clean": passed_clean,
        "stopped_3": blocked_3 + passed_clean,
        "winners": winners,
        "errors": errors,
        "done": done,
    }


def _badges_node_1(players: list[PlayerRecord]) -> list[str]:
    active: list[str] = []
    blocked: list[str] = []
    errors: list[str] = []
    passed: list[str] = []
    for p in players:
        nome = _nome_seguro(p.username)
        if p.status is S.AT_NODE_1:
            active.append(_badge(f"⏳ {nome}", "badge-active-1", "Analisando entrada..."))
        elif p.status is S.BLOCKED_NODE_1:
            blocked.append(_badge(f"🛑 {nome} — Retido no Nó 1", "badge-blocked-1", p.node_1_output))
        elif p.status is S.ERROR and _error_node(p) == 1:
            errors.append(_badge(f"❌ {nome} — Erro técnico", "badge-error", p.final_response))
        elif p.passed_node_1:
            passed.append(_badge(f"✓ {nome}", "badge-passed", p.node_1_output))
    return active + blocked + errors + passed


def _badges_node_2(players: list[PlayerRecord]) -> list[str]:
    active: list[str] = []
    errors: list[str] = []
    passed: list[str] = []
    for p in players:
        nome = _nome_seguro(p.username)
        if p.status is S.AT_NODE_2:
            active.append(_badge(f"⚙️ {nome}", "badge-active-2", "Gerando resposta no Core Agent..."))
        elif p.status is S.ERROR and _error_node(p) == 2:
            errors.append(_badge(f"❌ {nome} — Erro técnico", "badge-error", p.final_response))
        elif p.passed_node_2:
            passed.append(_badge(f"✓ {nome}", "badge-passed", "Passou para o DLP (Nó 3)"))
    return active + errors + passed


def _badges_node_3(players: list[PlayerRecord]) -> list[str]:
    active: list[str] = []
    blocked: list[str] = []
    clean: list[str] = []
    errors: list[str] = []
    passed: list[str] = []
    for p in players:
        nome = _nome_seguro(p.username)
        if p.status is S.AT_NODE_3:
            active.append(_badge(f"🔍 {nome}", "badge-active-3", "Auditando resposta no DLP..."))
        elif p.status is S.BLOCKED_NODE_3:
            blocked.append(_badge(f"⚠️ {nome} — Barrado no DLP", "badge-blocked-3", p.node_3_output))
        elif p.status is S.PASSED_CLEAN:
            clean.append(
                _badge(f"💬 {nome} — Passou Limpo (Sem Vazamento)", "badge-clean", p.node_3_output)
            )
        elif p.status is S.ERROR and _error_node(p) == 3:
            errors.append(_badge(f"❌ {nome} — Erro técnico", "badge-error", p.final_response))
        elif p.status is S.WINNER:
            passed.append(_badge(f"✓ {nome}", "badge-passed", "Passou pelo DLP com a chave!"))
    return active + blocked + clean + errors + passed


def _badges_winners(players: list[PlayerRecord]) -> list[str]:
    return [
        _badge(f"🏆 {_nome_seguro(p.username)}", "badge-winner", "Capturou a palavra-chave!")
        for p in players
        if p.status is S.WINNER
    ]


def _render_node_row(
    step_tag: str,
    title: str,
    subtitle_html: str,
    icon: str,
    badges: list[str],
    empty_msg: str,
    *,
    is_final: bool = False,
) -> str:
    card_cls = "arena-node-info arena-winner-card" if is_final else "arena-node-info"
    icon_cls = "arena-node-icon arena-winner-icon" if is_final else "arena-node-icon"
    box_cls = "arena-players-box arena-winner-box" if is_final else "arena-players-box"
    body = "".join(badges) if badges else f'<span class="arena-empty">{empty_msg}</span>'

    row_html = (
        '<div class="arena-row">'
        f'<div class="{card_cls}">'
        f'<div class="arena-step-tag">{step_tag}</div>'
        f'<div class="arena-node-title">{title}</div>'
        f'<div class="arena-node-sub">{subtitle_html}</div>'
        "</div>"
        '<div class="arena-center">'
        f'<div class="{icon_cls}">{icon}</div>'
        "</div>"
        f'<div class="{box_cls}">{body}</div>'
        "</div>"
    )
    if is_final:
        return row_html
    connector_html = (
        '<div class="arena-connector-row">'
        "<div></div>"
        '<div class="arena-connector-col"><span class="arena-arrow">↓</span></div>'
        "<div></div>"
        "</div>"
    )
    return row_html + connector_html


def build_graph_html(players: list[PlayerRecord], phase: GamePhase) -> str:
    """Monta o HTML completo do grafo vertical (sem indentação Markdown para não virar bloco de código)."""
    parts: list[str] = ['<div class="arena-graph">']

    waiting = [p for p in players if p.status is S.WAITING_START]
    if waiting:
        q_badges = "".join(
            _badge(f"🚦 {_nome_seguro(p.username)}", "badge-queue", "Aguardando slot na fila")
            for p in waiting
        )
        parts.append(
            '<div class="arena-queue-bar">'
            f'<span class="arena-queue-label">Na fila de largada ({len(waiting)}):</span>'
            f"{q_badges}"
            "</div>"
        )

    parts.append(
        _render_node_row(
            step_tag="Etapa 1",
            title="Nó 1 — Input Guardrail",
            subtitle_html=f"Filtro de Prompt Injection (<code>{GROQ_MODEL_LABEL}</code> + Heurística)",
            icon="🛡️",
            badges=_badges_node_1(players),
            empty_msg="Nenhum participante neste nó no momento.",
        )
    )
    parts.append(
        _render_node_row(
            step_tag="Etapa 2",
            title="Nó 2 — Core Agent (O Cofre)",
            subtitle_html=f"Processamento do Segredo (<code>{GEMINI_MODEL_LABEL}</code>)",
            icon="🔐",
            badges=_badges_node_2(players),
            empty_msg="Nenhum participante chegou ao Core Agent ainda.",
        )
    )
    parts.append(
        _render_node_row(
            step_tag="Etapa 3",
            title="Nó 3 — Output Guardrail (DLP)",
            subtitle_html=f"Auditoria de Saída (<code>{GROQ_MODEL_LABEL}</code> + DLP)",
            icon="🕵️",
            badges=_badges_node_3(players),
            empty_msg="Nenhuma resposta auditada pelo DLP ainda.",
        )
    )

    winners_empty = (
        "🛡️ Nenhum vencedor até o momento — Os Guardrails venceram!"
        if phase is GamePhase.FINISHED
        else "⏳ Aguardando participantes cruzarem todos os nós..."
    )
    parts.append(
        _render_node_row(
            step_tag="Etapa Final",
            title="🏆 Vencedores",
            subtitle_html="Passaram por todos os nós e extraíram a palavra-chave secreta",
            icon="🏆",
            badges=_badges_winners(players),
            empty_msg=winners_empty,
            is_final=True,
        )
    )

    parts.append("</div>")
    return "".join(parts)


# -------------------------------------------------------------------- tela
store = get_store()

# Sem palavra-chave definida não há partida: volta para a Tela 1.
if store.phase is GamePhase.SETUP:
    st.switch_page("views/tela_1_inicio.py")

FASE_RENDERIZADA = store.phase

st.markdown(GRAPH_CSS, unsafe_allow_html=True)
st.markdown(
    "<h1 style='text-align: center;'>🏟️ Teaming Arena — Grafo em Tempo Real (TELA 4)</h1>",
    unsafe_allow_html=True,
)

if FASE_RENDERIZADA is GamePhase.LOBBY:
    st.info("⏳ A rodada ainda está no Lobby aguardando o botão **PLAY** na Tela 2.")
    if st.button("⬅️ Voltar ao Lobby (Tela 2)", type="primary"):
        st.switch_page("views/tela_2_lobby.py")

    @st.fragment(run_every="1.5s")
    def _aguardar_play() -> None:
        if store.phase is not GamePhase.LOBBY:
            st.rerun(scope="app")

    _aguardar_play()
    st.stop()


@st.fragment(run_every="1s" if FASE_RENDERIZADA is GamePhase.RUNNING else "3s")
def _painel_ao_vivo() -> None:
    phase, _, players = store.get_snapshot()  # a palavra secreta nunca vai para o telão aqui
    if phase is not FASE_RENDERIZADA:
        st.rerun(scope="app")

    m = _compute_metrics(players)

    if phase is GamePhase.RUNNING:
        progresso = m["done"] / m["total"] if m["total"] else 0.0
        st.progress(
            progresso,
            text=f"⚡ Rodada em andamento — {m['done']} de {m['total']} participantes concluídos",
        )
    else:
        st.success(f"🏁 Rodada finalizada! Todos os {m['total']} participantes passaram pelo pipeline.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total de Inscritos", m["total"])
    c2.metric("Barrados no Nó 1 (Input)", m["blocked_1"])
    c3.metric(
        "Barrados / Sem Chave no Nó 3",
        m["stopped_3"],
        help=f"Barrados pelo DLP: {m['blocked_3']} | Passou Limpo (sem chave): {m['passed_clean']}",
    )
    c4.metric("🏆 Vencedores (Jailbreak)", m["winners"])

    if m["errors"]:
        st.caption(f"⚠️ {m['errors']} participante(s) tiveram falha técnica nas APIs.")

    st.markdown(build_graph_html(players, phase), unsafe_allow_html=True)


_painel_ao_vivo()

# ------------------------------------------------------------------ rodapé
st.divider()

with st.expander("🔎 Inspecionar Prompts e Respostas da Rodada", expanded=False):
    phase_insp, secret_insp, players_insp = store.get_snapshot()

    col_f1, col_f2 = st.columns([3, 1])
    with col_f1:
        filtro = st.selectbox(
            "Filtrar por resultado:",
            options=[
                "Todos",
                "🏆 Vencedores",
                "🛑 Barrados no Nó 1",
                "⚠️ Barrados no DLP (Nó 3)",
                "💬 Passou Limpo",
                "❌ Erro técnico",
                "⏳ Em andamento / Fila",
            ],
            key="tela4_filtro_insp",
        )
    with col_f2:
        st.write("")
        if st.button("🔄 Atualizar lista", use_container_width=True):
            st.rerun()

    def _bate_filtro(p: PlayerRecord) -> bool:
        if filtro == "Todos":
            return True
        if filtro == "🏆 Vencedores":
            return p.status is S.WINNER
        if filtro == "🛑 Barrados no Nó 1":
            return p.status is S.BLOCKED_NODE_1
        if filtro == "⚠️ Barrados no DLP (Nó 3)":
            return p.status is S.BLOCKED_NODE_3
        if filtro == "💬 Passou Limpo":
            return p.status is S.PASSED_CLEAN
        if filtro == "❌ Erro técnico":
            return p.status is S.ERROR
        return p.status not in TERMINAL_STATUSES

    filtrados = [p for p in players_insp if _bate_filtro(p)]

    if not filtrados:
        st.caption("Nenhum participante corresponde ao filtro selecionado.")
    else:
        escolhido = st.selectbox(
            "Escolha um participante para inspecionar:",
            options=filtrados,
            format_func=lambda p: (
                f"{html.unescape(p.username)} — {STATUS_LABELS.get(p.status, p.status.value)}"
            ),
            key="tela4_jogador_insp",
        )
        if escolhido is not None:
            latencia = f"{escolhido.latency_ms} ms" if escolhido.latency_ms else "em processamento"
            st.markdown(
                f"**Participante:** {_nome_seguro(escolhido.username)} | "
                f"**Status:** {STATUS_LABELS.get(escolhido.status, escolhido.status.value)} | "
                f"**Tempo:** {latencia}",
                unsafe_allow_html=True,
            )
            st.markdown("**Prompt enviado:**")
            st.text(escolhido.prompt)
            if escolhido.node_1_output:
                st.markdown("**Nó 1 (Input Guardrail):**")
                st.caption(escolhido.node_1_output)
            if escolhido.node_2_output:
                st.markdown("**Nó 2 (Saída do Core Agent):**")
                st.text(escolhido.node_2_output)
            if escolhido.node_3_output:
                st.markdown("**Nó 3 (Output DLP):**")
                st.caption(escolhido.node_3_output)
            if escolhido.final_response:
                st.markdown("**Resposta final entregue ao jogador:**")
                st.text(escolhido.final_response)

    if phase_insp is GamePhase.FINISHED and secret_insp:
        st.divider()
        if st.toggle("🔓 Revelar palavra-chave desta rodada no telão", value=False):
            st.markdown("🔑 **Palavra-chave secreta da rodada:**")
            st.code(secret_insp, language=None)

if st.button("🔄 Encerrar e Voltar para a Tela 1 (Nova Palavra-Chave)"):
    store.reset_to_setup()
    st.switch_page("views/tela_1_inicio.py")
