# PledgeCity

Plataforma com duas secoes:

- `Missoes Oferecidas`: usuario publica o que faria por uma meta e recebe pledges.
- `Pedidos em Leilao Reverso`: usuario publica o que quer que seja feito, pessoas ofertam por quanto fariam, e o menor valor predomina.

## Recursos principais

- Login e senha por usuario.
- Pledges e posts com username do login.
- Prazo com data + hora em horario de Brasilia (`America/Sao_Paulo`).
- Commit parcial na missao oferecida (`commit no valor atual`).
- Grupos com dono, convites e aprovacao pelo criador.
- Alcance por `aberto`, `grupo inteiro` ou `usuarios especificos`.
- Saldo automatico:
  - `Voce deve`
  - `Voce recebe`
  - `Declarar recebido` (somente quem recebe pode encerrar o item).
- Termos e condicoes na interface.

## Banco e persistencia

- Em producao, use Postgres via `DATABASE_URL`.
- No Render, use o `render.yaml` com web service + banco.
- Dados nao devem ser perdidos em restart/deploy normal quando o Postgres estiver ativo.

## Rodar localmente

```bash
cd /Applications/pledge-challenges
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Abra `http://127.0.0.1:4173`.
