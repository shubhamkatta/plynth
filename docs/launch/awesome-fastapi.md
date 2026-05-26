# awesome-fastapi submission

## 1. Target repo and section

Repo: https://github.com/mjhea0/awesome-fastapi

PRs add a single bullet under an existing section in `README.md`.
Plynth fits **Boilerplate** (full backend scaffold). Secondary:
**Open Source Projects / Full Stack**. Sort alphabetically within
the section.

## 2. Exact line to add

Recommended:

```
- [Plynth](https://github.com/shubhamkatta/plynth) - Multi-tenant multi-product SaaS backend scaffold with RBAC, billing, credits, jobs and storage APIs.
```

Alternatives:

```
- [Plynth](https://github.com/shubhamkatta/plynth) - Async FastAPI + SQLAlchemy 2.0 multi-tenant SaaS scaffold: auth, RBAC, billing, credits, webhooks.
```

```
- [Plynth](https://github.com/shubhamkatta/plynth) - Production-ready multi-product SaaS backend on FastAPI with Postgres, Redis, arq, and an Electron admin client.
```

## 3. PR title

```
Add Plynth to Boilerplate
```

## 4. PR body

```markdown
Adding [Plynth](https://github.com/shubhamkatta/plynth), an open-source
multi-tenant multi-product SaaS backend scaffold on FastAPI. It gives
developers a reusable platform layer (auth, RBAC, billing, credits,
audit) so they can ship many SaaS products from one deployment.

Why it fits awesome-fastapi (Boilerplate):

- FastAPI + async SQLAlchemy 2.0 + Pydantic v2, fully async stack
- Postgres + Redis + arq for background jobs
- JWT auth + per-product RBAC with permission codes
- Pluggable billing provider (Stripe driver included) and credits ledger
- Designed Jobs API and Storage API for desktop/edge clients
- Electron admin client and Next.js starter consume only the documented REST API
- CLI for bootstrapping new products and tenants

Meets the contribution requirements:

- MIT licensed
- Active maintenance (recent commits on `main`)
- Clear README with quickstart, architecture, and contribution guide
- Full docs at https://shubhamkatta.github.io/plynth/
- Entry added alphabetically in the Boilerplate section
```

## 5. Pre-submit checklist

- [ ] README has install + quickstart at the top
- [ ] LICENSE file present and visible (MIT)
- [ ] Commits on `main` within the last 30 days
- [ ] CI badge is green on the README
- [ ] `grep -i plynth README.md` on awesome-fastapi returns nothing
- [ ] New line inserted alphabetically within the Boilerplate section
- [ ] Description under ~100 chars, no marketing words, ends with a period
- [ ] Docs site loads: https://shubhamkatta.github.io/plynth/

## 6. Other awesome lists to target next

- **awesome-saas-boilerplates** — https://github.com/smirnov-am/awesome-saas-boilerplates — SaaS starters across stacks. Strong fit.
- **awesome-multitenancy** — https://github.com/Hopding/awesome-multi-tenancy — multi-tenant patterns and projects. Good fit.
- **awesome-python** — https://github.com/vinta/awesome-python — "Web Frameworks" or "RESTful API". Stretch; prefers libraries.
- **awesome-electron** — https://github.com/sindresorhus/awesome-electron — only when `apps/admin-electron/` ships a signed installer as its own repo.
- **awesome-selfhosted** — https://github.com/awesome-selfhosted/awesome-selfhosted — end-user apps only. Skip unless you ship a turnkey product on top.

## 7. Fork and PR commands

```bash
# 1. Fork and clone
gh repo fork mjhea0/awesome-fastapi --clone=true --remote=true
cd awesome-fastapi

# 2. Branch
git checkout -b add-plynth

# 3. Edit README.md - insert the line alphabetically under Boilerplate
$EDITOR README.md

# 4. Commit
git add README.md
git commit -m "Add Plynth to Boilerplate"

# 5. Push to your fork
git push -u origin add-plynth

# 6. Open PR against upstream main
gh pr create \
  --repo mjhea0/awesome-fastapi \
  --base main \
  --head "$(gh api user -q .login):add-plynth" \
  --title "Add Plynth to Boilerplate" \
  --body-file - <<'EOF'
Adding Plynth, an open-source multi-tenant multi-product SaaS backend
scaffold built on FastAPI. It provides auth, RBAC, billing, credits,
jobs, storage, and an Electron admin client out of the box.

- MIT licensed
- Active on main
- README + docs at https://shubhamkatta.github.io/plynth/
- Inserted alphabetically under Boilerplate
EOF
```
