# PledgeCity (versao online)

Agora o projeto roda com backend Flask + banco SQLite, entao os dados sao compartilhados entre usuarios no mesmo servidor.

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

## Deploy gratis no Render

1. Suba esta pasta para um repositório no GitHub.
2. Entre no Render: [https://render.com](https://render.com)
3. Clique em `New +` > `Blueprint` e selecione seu repo.
4. O Render vai ler o arquivo `render.yaml` automaticamente.
5. Conclua a criacao. Ele vai gerar uma URL publica tipo:
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

- `app.py`: backend (API + servidor web)
- `index.html`, `styles.css`, `app.js`: frontend
- `data.db`: banco SQLite (criado automaticamente ao iniciar)
- `render.yaml`: configuracao de deploy

## Observacoes importantes

- No plano gratis do Render, a aplicacao pode "dormir" e demorar alguns segundos no primeiro acesso.
- SQLite funciona para MVP. Para crescer (muitos usuarios), migrar para PostgreSQL.
- Ainda nao ha pagamentos reais; pledge aqui e compromisso social.
