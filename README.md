# JC Moda Masculina - API

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
- Política de privacidade automática (ou personalizada) e anonimização diária dos dados de pedidos encerrados há mais de 12 meses

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
| `BLOB_STORE_ID` | Vercel Blob para armazenar as imagens (criada ao conectar o Blob Store). Se omitida, as imagens ficam em `static/uploads` |
| `CRON_SECRET` | Senha das tarefas agendadas da Vercel (`/api/cron/*`) |

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
| `GET /api/auth/google` | ID do cliente do "Entrar com Google" (`null` = desligado) |
| `POST /api/auth/google` | Login no painel com conta Google (só e-mails de administradores já cadastrados) |
| `/api/admin/...` | Rotas do painel (requerem autenticação) |

A lista completa está na documentação interativa (`/docs`).

## Implantação

### Vercel

O projeto já está preparado para a Vercel (`vercel.json`, `.python-version`). A Vercel detecta o
FastAPI em `app/main.py` automaticamente.

1. Importe o repositório na Vercel.
2. Em **Storage**, crie um **Blob Store** público e conecte ao projeto (isso cria `BLOB_STORE_ID`).
3. Em **Settings → Environment Variables**, cadastre:

   | Variável | Valor |
   |---|---|
   | `ENVIRONMENT` | `production` |
   | `DATABASE_URL` / `DATABASE_URL_UNPOOLED` | URLs do banco PostgreSQL |
   | `SECRET_KEY` | valor longo e aleatório |
   | `CORS_ORIGINS` | endereço do site, ex.: `["https://www.seudominio.com.br"]` |
   | `CRON_SECRET` | valor longo e aleatório |
   | `ADMIN_EMAIL` / `ADMIN_PASSWORD` | apenas se o banco ainda não tiver administrador |

4. Faça o deploy. A tarefa agendada em `vercel.json` cancela diariamente os pedidos não pagos
   dentro do prazo configurado; a loja também faz essa verificação durante o uso.

Limitações na Vercel:

- Imagens enviadas pelo painel têm limite de 4 MB.
- O limite de requisições fica na memória de cada instância. Para um limite global, use um
  armazenamento compartilhado, como Redis.

### Servidor próprio

1. Crie o arquivo `.env` com `ENVIRONMENT=production`, uma `SECRET_KEY` própria e o domínio do
   site em `CORS_ORIGINS`.
2. Execute a API atrás de um servidor web com HTTPS (por exemplo, Nginx):

   ```bash
   uvicorn app.main:app --proxy-headers --forwarded-allow-ips="127.0.0.1" --workers 1
   ```

3. Mantenha backup do banco de dados e da pasta `static/uploads`.

Em modo de produção, a API não inicia com configurações padrão inseguras, desativa a documentação
pública e exige autenticação em duas etapas no painel.

### Publicação automática (GitHub Actions)

A cada push na `main`, o workflow `.github/workflows/publicar.yml` confere se o código abre sem erro
e, se estiver tudo certo, entra no servidor por SSH e roda `deploy/atualizar.sh` (baixa o código,
instala dependências, reinicia a API e confere se ela voltou). Se a conferência falhar, o servidor
continua com a versão anterior. Também dá para publicar à mão em **Actions > Publicar no servidor >
Run workflow**.

Configuração única, no ambiente **VPS_HOST** do repositório (**Settings > Environments > VPS_HOST**;
o workflow usa `environment: VPS_HOST`):

| Nome | Tipo | Valor |
| --- | --- | --- |
| `VPS_HOST` | Secret | IP do servidor |
| `VPS_USER` | Secret | usuário do SSH (na Oracle Cloud: `ubuntu`) |
| `VPS_PATH` | Secret | caminho da pasta `backend` no servidor (ex.: `/home/ubuntu/JC-Moda/backend`) |
| `VPS_SSH_KEY` | Secret | chave privada de deploy (conteúdo inteiro do arquivo) |
| `API_URL` | Variable | endereço público da API, para a conferência final (opcional) |

A identidade pública do servidor fica em `deploy/known_hosts` (não é segredo; se o servidor for
recriado, atualize com `ssh-keyscan IP`). A chave pública de deploy vai no `~/.ssh/authorized_keys` do servidor. Use uma chave só para
isso: se precisar, ela pode ser removida sem afetar o acesso de ninguém. O usuário precisa poder
rodar `sudo systemctl restart jcmoda-api` sem senha (padrão na Oracle Cloud).

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
