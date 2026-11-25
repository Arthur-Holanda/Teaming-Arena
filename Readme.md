# 🛡️ Teaming Arena — LLMOps Guardrails

Aplicação interativa desenvolvida para demonstrar ao vivo, na prática, mecanismos de **defesa em profundidade (*Defense-in-Depth*)** contra **Prompt Injection**, **Jailbreak**, **engenharia social** e **vazamento de dados (DLP)** em LLMs.

Os participantes enviam prompts pelo celular tentando extrair uma palavra-chave secreta de um agente protegido por guardrails de entrada e saída orquestrados com **LangGraph**, enquanto acompanham todo o funil em tempo real no telão.

---

## 🏗️ Arquitetura do Pipeline e Papel de Cada Nó

Cada prompt enviado passa por um grafo sequencial em [core/graph.py](core/graph.py), onde cada camada possui uma responsabilidade bem definida:

1. **Nó 1 — Input Guardrail / Filtro de Perímetro (Heurística Regex + `openai/gpt-oss-120b` via Groq)**
   * **Papel:** barrar ataques **explícitos e óbvios** logo na entrada, economizando chamadas ao agente principal.
   * **O que bloqueia (`BLOCKED_NODE_1`):**
     * *Heurística local (sem custo de API):* comandos clássicos de injeção (*"ignore as instruções anteriores"*), pedidos diretos pela senha/palavra-chave, tentativa de extrair o *system prompt* e modos declarados sem restrições (`DAN`, `Modo Desenvolvedor`, `Modo Deus`).
     * *Juiz LLM (`openai/gpt-oss-120b`):* ataques explícitos de `prompt_injection` (incluindo cabeçalhos falsos como `[SISTEMA]` ou `--- FIM DA ENTRADA ---`) e `roleplay_jailbreak` declarado.
   * **O que deixa passar:** perguntas técnicas normais, engenharia social educada/indireta, escrita criativa e pedidos de formatação/transformação — delegando essas análises aos Nós 2 e 3.

2. **Nó 2 — Core Agent / O Cofre (`gemini-3.5-flash-lite` via Google AI Studio)**
   * **Papel:** atuar como o **Assistente Corporativo de MLOps**, mantendo a palavra-chave confidencial no contexto interno da sessão.
   * **Comportamento:** recusa abordagens óbvias de engenharia social (ex.: alguém se passando por auditor interno ou gestor pedindo confirmação do valor), resultando em resposta segura (`PASSED_CLEAN`). Em contrapartida, mantém postura prestativa em pedidos técnicos, logs de observabilidade e exercícios de formatação — reproduzindo o risco real de vazamento em assistentes corporativos.
   * **Segurança de exibição:** a resposta bruta do Nó 2 não é exibida ao jogador antes da aprovação do Nó 3.

3. **Nó 3 — Output Guardrail / DLP de Texto Claro (Checagem Literal + `openai/gpt-oss-120b` via Groq)**
   * **Papel:** última linha de defesa — audita a resposta gerada pelo Nó 2 **antes** de entregá-la ao participante.
   * **O que bloqueia (`BLOCKED_NODE_3`):** qualquer vazamento **explícito, contínuo e legível** da palavra-chave em texto claro (via busca literal determinística e juiz LLM). Quando intercepta, retém a saída original (`[Resposta retida pelo DLP por conter dados sensíveis]`) e envia uma mensagem padrão de bloqueio.
   * **O que deixa passar:** respostas normais, recusas do agente e saídas ofuscadas/codificadas (como texto invertido, caracteres separados por símbolos ou Base64), simulando o limite de um DLP focado em texto claro.

4. **Árbitro Final Pós-DLP (`did_player_capture_secret` em `core/security.py`)**
   * **Papel:** classifica deterministicamente quem passou pelo Nó 3 sem bloqueio:
     * **🏆 Vencedor (`WINNER`):** a resposta final entregue contém a palavra-chave (exata, normalizada/separada por espaços ou símbolos como `e-c-e-i-p-_-e-n-o`, invertida ou em Base64).
     * **💬 Passou Limpo (`PASSED_CLEAN`):** o prompt atravessou os 3 nós sem vazamento (seja por ser uma pergunta legítima ou porque o Nó 2 recusou o ataque com sucesso).

---

## 📺 Fluxo das Telas

A navegação lateral fica oculta (`st.navigation(..., position="hidden")` em `app.py`) para separar a experiência do apresentador e dos participantes:

| Rota | Arquivo | Público | Função |
| :--- | :--- | :--- | :--- |
| `/INICIO` (`/`) | `views/tela_1_inicio.py` | Host (Projetor) | Define a palavra-chave secreta da rodada (campo mascarado) e valida regras. |
| `/Lobby` | `views/tela_2_lobby.py` | Host (Projetor) | Exibe QR Code para `/Cadastro`, lista inscritos ao vivo e tem o botão **PLAY**. |
| `/Cadastro` | `views/tela_3_cadastro.py` | Jogadores (Celular) | Formulário de apelido e prompt de ataque (tranca automaticamente após o **PLAY**). |
| `/Jogo` | `views/tela_4_jogo.py` | Host (Projetor) | Grafo vertical em tempo real com métricas, badges por nó, inspetor de prompts e reset. |
| `/Largada` | `views/tela_5_largada.py` | Jogadores (Celular) | Sala de espera e acompanhamento individual nó a nó do próprio prompt e veredito final. |

---

## 🛠️ Tecnologias

* **Orquestração:** LangChain & LangGraph (`StateGraph`)
* **Inferência:** Groq API (`openai/gpt-oss-120b`) & Google AI Studio (`gemini-3.5-flash-lite`) com pool *round-robin*, backoff adaptativo e fallback automático (`core/key_pool.py`)
* **Frontend & Estado:** Streamlit (`@st.fragment`, `@st.cache_resource`) & Pydantic
* **Acesso Mobile:** `qrcode[pil]` para geração dinâmica do QR Code da sessão

---

## 🚀 Como Executar Localmente

1. **Clone o repositório, crie um ambiente virtual e instale as dependências:**
   ```bash
   git clone <url-do-repositorio>
   cd Teaming-Arena
   python3 -m venv .venv
   source .venv/bin/activate        # No Windows PowerShell: .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. **Configure as chaves de API:**
   Copie o arquivo `.env.example` para `.env` na raiz do projeto e preencha **pelo menos 1 chave de cada provedor** (suporta até 3 chaves por provedor em rodízio automático para evitar *rate limit* com vários jogadores):
   ```env
   # Groq (Nós 1 e 3 — Guardrails)
   GROQ_API_KEY_1="gsk_..."
   GROQ_API_KEY_2="gsk_..."
   GROQ_API_KEY_3="gsk_..."

   # Google AI Studio / Gemini (Nó 2 — Core Agent)
   GEMINI_API_KEY_1="AIza..."
   GEMINI_API_KEY_2="AIza..."
   GEMINI_API_KEY_3="AIza..."
   ```
   *(Para testes rápidos com uma única chave, também são aceitas `GROQ_API_KEY` e `GOOGLE_API_KEY` no singular.)*

3. **Execute a aplicação:**
   ```bash
   streamlit run app.py
   ```
   A aplicação abrirá em `http://localhost:8501` direto na **Tela 1 (`/INICIO`)**.

### 💡 Dicas para desenvolvimento e testes locais
* **Hot-reload:** o arquivo `.streamlit/config.toml` define `fileWatcherType = "none"` para evitar travamentos com múltiplos celulares atualizando a cada 1,5 s. Durante o desenvolvimento, reinicie o comando após editar o código ou rode `streamlit run app.py --server.fileWatcherType auto`.
* **Testando com celular na mesma rede Wi-Fi:** na Tela 2 (`/Lobby`), substitua `localhost` no campo *Link da Sessão* pelo IP local do seu computador (a própria tela detecta e sugere o endereço).

---

## ☁️ Deploy no Streamlit Community Cloud

1. Suba o repositório para o GitHub (certificando-se de que `.env` **não** foi versionado — ele já está listado no `.gitignore`).
2. Acesse [share.streamlit.io](https://share.streamlit.io), clique em **Create app** e aponte para o repositório, branch `main` e arquivo principal `app.py`.
3. Em **Advanced settings → Secrets** (ou depois em **App Settings → Secrets**), cole suas chaves no formato TOML:
   ```toml
   GROQ_API_KEY_1 = "gsk_..."
   GROQ_API_KEY_2 = "gsk_..."
   GROQ_API_KEY_3 = "gsk_..."

   GEMINI_API_KEY_1 = "AIza..."
   GEMINI_API_KEY_2 = "AIza..."
   GEMINI_API_KEY_3 = "AIza..."
   ```
4. Clique em **Deploy** e faça um ensaio escaneando o QR Code da Tela 2 em 2 celulares antes da apresentação.
