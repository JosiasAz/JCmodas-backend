# JC Moda Masculina — API

API REST da loja virtual **JC Moda Masculina**. Fornece os dados da vitrine, calcula preços e
fretes, registra pedidos e atende o painel administrativo da loja.

O site (front-end) é mantido em um repositório separado e consome esta API.

## Funcionalidades

- Catálogo de produtos com categorias, variações de cor e tamanho e controle de estoque
- Promoções, cupons de desconto, combos e anúncios com agendamento
- Cálculo de carrinho, frete e descontos feito inteiramente no servidor
- Registro e acompanhamento de pedidos
- Painel administrativo com autenticação em duas etapas, gestão de usuários e histórico de alterações
- Upload de imagens de produtos
- Política de privacidade configurável e anonimização de dados de pedidos antigos

## Tecnologias

- [Python](https://www.python.org/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [Pydantic](https://docs.pydantic.dev/)
- [PostgreSQL](https://www.postgresql.org/) (ou SQLite para desenvolvimento local)

## Pré-requisitos

- Python 3.12 ou superior
- PostgreSQL (opcional; sem ele a API usa um banco SQLite local)

## Instalação

```bash
git clone <url-do-repositorio>
cd <pasta-do-repositorio>

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

## Configuração

Copie o arquivo de exemplo e preencha os valores:

```bash
cp .env.example .env
```

| Variável | Descrição |
|---|---|
| `ENVIRONMENT` | `development` ou `production` |
| `DATABASE_URL` | URL de conexão com o banco. Se omitida, usa SQLite (`jcmoda.db`) |
| `DATABASE_URL_UNPOOLED` | Conexão direta com o banco, usada para criar e atualizar tabelas (opcional) |
| `SECRET_KEY` | Chave usada para assinar as sessões. Use um valor longo e aleatório |
| `CORS_ORIGINS` | Lista de endereços autorizados a acessar a API, ex.: `["http://localhost:4200"]` |
| `ADMIN_EMAIL` | E-mail do primeiro administrador |
| `ADMIN_PASSWORD` | Senha do primeiro administrador (usada apenas na criação) |

Para gerar uma `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Para o ambiente de produção, use como base o arquivo `.env.production.example`.

## Execução

```bash
uvicorn app.main:app --reload --port 8000
```

Na primeira execução, as tabelas são criadas automaticamente e o administrador definido no `.env`
é cadastrado. A loja começa vazia; produtos, categorias e configurações são cadastrados pelo painel.

A documentação interativa da API fica disponível em http://localhost:8000/docs (somente em
ambiente de desenvolvimento).

## Dados de exemplo

| Comando | Descrição |
|---|---|
| `python -m app.seed --demo` | Adiciona produtos, promoções e anúncios fictícios para testes |
| `python -m app.seed --clear` | Remove catálogo, marketing e pedidos, mantendo os usuários |
| `python -m app.seed --reset` | Apaga todos os dados e recria o banco |

## Estrutura do projeto

```
app/
├── core/       # configuração, banco de dados e autenticação
├── models/     # tabelas do banco de dados
├── schemas/    # validação de entrada e saída
├── services/   # regras de negócio (preços, pedidos)
├── routers/    # rotas da API
├── seed/       # criação inicial de dados
└── main.py     # ponto de entrada da aplicação
static/
└── uploads/    # imagens enviadas pelo painel
```

## Principais rotas

| Rota | Descrição |
|---|---|
| `GET /api/products` | Lista de produtos com filtros |
| `POST /api/cart/quote` | Calcula o valor do carrinho |
| `POST /api/orders` | Cria um pedido |
| `POST /api/orders/track` | Consulta o andamento de um pedido |
| `POST /api/auth/login` | Login no painel administrativo |
| `/api/admin/...` | Rotas do painel (requerem autenticação) |

A lista completa está na documentação interativa (`/docs`).

## Implantação

1. Crie o arquivo `.env` com `ENVIRONMENT=production`, uma `SECRET_KEY` própria e o domínio do
   site em `CORS_ORIGINS`.
2. Execute a API atrás de um servidor web com HTTPS (por exemplo, Nginx):

   ```bash
   uvicorn app.main:app --proxy-headers --forwarded-allow-ips="127.0.0.1" --workers 1
   ```

3. Mantenha backup do banco de dados e da pasta `static/uploads`.

Em modo de produção, a API não inicia com configurações padrão inseguras, desativa a documentação
pública e exige autenticação em duas etapas no painel.

## Segurança

- Preços e descontos são sempre recalculados no servidor
- Limite de requisições e bloqueio temporário após tentativas de login malsucedidas
- Senhas armazenadas com hash e autenticação em duas etapas
- Validação de todos os dados recebidos e das imagens enviadas
- Registro das alterações feitas no painel

Para relatar uma vulnerabilidade, entre em contato diretamente com o responsável pelo projeto em vez
de abrir uma issue pública.

## Licença

Projeto proprietário. Todos os direitos reservados. Consulte o arquivo [LICENSE](LICENSE).
