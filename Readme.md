#  Teaming Arena — LLMOps Guardrails

Aplicação interativa desenvolvida para demonstrar na prática mecanismos de defesa em profundidade (*Defense-in-Depth*) contra **Prompt Injection**, **Jailbreak** e **vazamento de dados** em LLMs[cite: 1]. 

Os participantes enviam prompts pelo celular tentando extrair uma palavra-chave secreta de um agente protegido por guardrails de entrada e saída orquestrados com **LangGraph**, acompanhando o fluxo em tempo real no telão.

## 🏗️ Arquitetura do Pipeline

1. **Nó 1 — Input Guardrail (`llama-3.1-8b-instant` via Groq):** Filtra tentativas óbvias de *Prompt Injection* e engenharia social na entrada[cite: 1].
2. **Nó 2 — Core Agent (`gemini-2.5-flash` via Google AI Studio):** Assistente que guarda a palavra-chave da rodada[cite: 1].
3. **Nó 3 — Output Guardrail / DLP (`llama-3.1-8b-instant` via Groq):** Audita a resposta gerada para barrar vazamentos antes de exibi-la ao usuário[cite: 1].

## 🛠️ Tecnologias

* **Orquestração:** LangChain & LangGraph[cite: 1]
* **Inferência:** Groq API & Google AI Studio (Gemini)[cite: 1]
* **Frontend & Estado:** Streamlit & Pydantic[cite: 1]

## 🚀 Como Executar Localmente

1. **Clone o repositório e instale as dependências:**
   ```bash
   git clone <url-do-repositorio>
   cd teaming-arena
   pip install -r requirements.txt