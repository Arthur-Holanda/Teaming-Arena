"""Ponto de entrada do Teaming Arena: roteador das 5 telas, sem menu lateral.

Rodar:  streamlit run app.py

Telas (cada uma é um arquivo em views/):
    INICIO    Host define a palavra-chave da rodada         (rota "/", é a página padrão)
    Lobby     Host mostra o QR Code e aperta PLAY           (/Lobby)
    Cadastro  Jogador envia nome e prompt de ataque         (/Cadastro)
    Jogo      Telão com o grafo em tempo real               (/Jogo)
    Largada   Jogador acompanha o próprio resultado         (/Largada)

A navegação fica oculta: o menu não aparece para ninguém, e as telas se chamam com
`st.switch_page("views/tela_X.py")` ou pelo endereço (o QR Code aponta para /Cadastro).
"""

import streamlit as st

# Precisa ser o primeiro comando Streamlit do app.
st.set_page_config(
    page_title="Teaming Arena — LLMOps",
    layout="wide",
    initial_sidebar_state="collapsed",
)

pages = [
    st.Page("views/tela_1_inicio.py", title="Início", url_path="INICIO", default=True),
    st.Page("views/tela_2_lobby.py", title="Lobby", url_path="Lobby"),
    st.Page("views/tela_3_cadastro.py", title="Cadastro", url_path="Cadastro"),
    st.Page("views/tela_4_jogo.py", title="Jogo", url_path="Jogo"),
    st.Page("views/tela_5_largada.py", title="Largada", url_path="Largada"),
]

pg = st.navigation(pages, position="hidden")
pg.run()
