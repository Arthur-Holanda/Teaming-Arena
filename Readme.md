#  Teaming Arena — LLMOps Guardrails

Aplicação interativa desenvolvida para demonstrar na prática mecanismos de defesa em profundidade (*Defense-in-Depth*) contra **Prompt Injection**, **Jailbreak** e **vazamento de dados** em LLMs. 

Os participantes enviam prompts pelo celular tentando extrair uma palavra-chave secreta de um agente protegido por guardrails de entrada e saída orquestrados com **LangGraph**, acompanhando o fluxo em tempo real no telão.

## 🏗️ Arquitetura do Pipeline

1. **Nó 1 — Input Guardrail (`openai/gpt-oss-120b` via Groq):** Filtra tentativas óbvias de *Prompt Injection* e engenharia social na entrada.
2. **Nó 2 — Core Agent (`gemini-2.5-flash` via Google AI Studio):** Assistente que guarda a palavra-chave da rodada.
3. **Nó 3 — Output Guardrail / DLP (`openai/gpt-oss-120b` via Groq):** Audita a resposta gerada para barrar vazamentos antes de exibi-la ao usuário.

## 🛠️ Tecnologias

* **Orquestração:** LangChain & LangGraph
* **Inferência:** Groq API & Google AI Studio (Gemini)
* **Frontend & Estado:** Streamlit & Pydantic

## 🚀 Como Executar Localmente

1. **Clone o repositório e instale as dependências:**
   ```bash
   git clone <url-do-repositorio>
   cd teaming-arena
   pip install -r requirements.txt