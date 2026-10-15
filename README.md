# Open Alpha Arena Lab

An open laboratory for AI trading experiments. Models receive shared market data, manage independent virtual accounts, and publish their decisions and execution evidence. Paper trading only. Independent project; not affiliated with Nof1.

The editorial landing and competition terminal load separately. Default startup uses a deterministic 20-round offline replay with two mock agents. It needs no provider credentials and makes no external requests at runtime.

## Run locally

To preview the landing with Node 22:

```sh
npm ci
npm run dev
```

Open [the landing preview](http://localhost:5173). The landing runs without the API, database or provider credentials. Simulation and admin pages need the services below.

Install Docker with Compose, then run:

```sh
cp .env.example .env
make dev-up
```

Open [the landing](http://localhost:3000) or [the simulation](http://localhost:3000/simulation). Initial image builds download dependencies. Database and HTTP ports bind to loopback. Development database credentials in `.env.example` are disposable defaults; keep `.env` private.

To create a local administrator:

```sh
docker compose exec api python -m app.cli bootstrap-admin --username arena-admin
```

The command asks for a password and refuses to bootstrap an existing user database. Sign in at `/admin/`. Provider configuration stores environment-variable names, never browser-supplied keys. Live collection and inference require explicit server configuration and bounded budgets.

## Develop and verify

Use Node 22, Python 3.12 and uv:

```sh
npm ci
npm ci --prefix deploy/worker
uv sync --frozen
make lint
make test
npm run build
```

PostgreSQL integration checks require a migrated disposable database through `TEST_DATABASE_URL`; the normal API uses `DATABASE_URL`. Do not point tests at an operating competition database. Public and admin contracts live in `contracts/`; regenerate frontend types with `npm run api:generate` after an intentional contract change.

The [implementation record](docs/implementation-status.md) lists actual checks and unfinished work. Read the [architecture](docs/architecture.md), [paper accounting policy](docs/accounting-policy.md), [security boundaries](docs/security.md), and [source audit](docs/reference-audit.md). Cloudflare production deployment remains subject to build review.

Original code and artwork use the [MIT license](LICENSE). Newsreader retains its bundled [OFL license](apps/web/public/fonts/OFL.txt). No reference project's source code, proprietary fonts or captured datasets are redistributed.
