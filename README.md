# PledgeCity (versao online)

Agora o projeto roda com backend Flask e suporta banco persistente via `DATABASE_URL` (Postgres recomendado no Render).
Inclui login/senha, controle por username, desafios com counteroffer e permissao de apagar por dono/admin.

## Rodar localmente

1. Abra terminal na pasta:
   - `cd /Applications/pledge-challenges`
2. Crie ambiente virtual:
   - `python3 -m venv .venv`
3. Ative:
   - `source .venv/bin/activate`
4. Instale dependencias:
   - `pip install -r requirements.txt`
5. Rode o app:
   - `python3 app.py`
6. Abra:
   - `http://127.0.0.1:4173`

## Deploy no Render com banco persistente

1. Suba esta pasta para um repositório no GitHub.
2. Entre no Render: [https://render.com](https://render.com)
3. Clique em `New +` > `Blueprint` e selecione seu repo.
4. O Render vai ler o arquivo `render.yaml` automaticamente e criar:
   - 1 Web Service (`pledgecity`)
   - 1 Postgres (`pledgecity-db`)
5. Conclua a criacao e aguarde o deploy. Ele vai gerar uma URL publica tipo:
   - `https://pledgecity.onrender.com`

Pronto: esse link publico pode ser enviado para outras pessoas entrarem e usarem juntos.

## Deploy simples no Railway (alternativa ao Render)

1. Suba o projeto no GitHub.
2. Entre em [https://railway.app](https://railway.app) e faca login com GitHub.
3. Clique em `New Project` > `Deploy from GitHub repo`.
4. Escolha `pledge-challenges`.
5. Railway detecta Python e sobe automaticamente.
6. Em `Settings` > `Networking`, gere dominio publico.
7. Abra a URL publica e compartilhe.

## Estrutura

- `app.py`: backend (API + servidor web) com SQLAlchemy
- `index.html`, `styles.css`, `app.js`: frontend
- `data.db`: fallback local para desenvolvimento (quando `DATABASE_URL` nao esta setada)
- `render.yaml`: configuracao de deploy

## Observacoes importantes

- No plano gratis do Render, a aplicacao pode "dormir" e demorar alguns segundos no primeiro acesso.
- Em producao no Render, os dados ficam persistidos no Postgres configurado no `render.yaml`.
- Ainda nao ha pagamentos reais; pledge aqui e compromisso social.
- Admin para apagar qualquer thread: username definido em `ADMIN_USERNAME` (padrao: `josephdayan`).
