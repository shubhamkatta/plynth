# plynth on AWS (OpenTofu / Terraform)

Moves plynth from the DigitalOcean droplet to the AWS account that already
hosts Mayva (`ap-south-1`). **Nothing here has been applied.** Review the plan,
then follow the order below.

## What it creates (11 resources, 0 changes to anything existing)

| Resource | Purpose |
|---|---|
| `aws_instance.app` (`t4g.small`, Ubuntu 24.04 arm64) + Elastic IP | the plynth box: Caddy + API + worker + Redis in Docker |
| `aws_security_group.app` | 80/443 in. **No SSH** — shell is SSM Session Manager |
| `aws_ecr_repository.plynth` (+ lifecycle) | images built in CI, immutable SHA tags |
| instance role + profile | SSM, ECR pull, SES send (only as `ses_from_address`) |
| `github_deploy` role | OIDC, this repo + `main` only; push to ECR + SSM deploy to this one instance |

It **looks up, never manages**: the default VPC, Mayva's RDS (`mayva-db`) and the
account's existing GitHub OIDC provider. The box is placed in the RDS's AZ.

Design notes
- AMI is **pinned** and the instance has `ignore_changes = [ami, user_data]` +
  termination protection. The box holds `/opt/plynth/.env`; a moved AMI must
  never replace it as a side effect (Mayva's stack hit exactly this).
- IMDSv2 required, hop limit 2 so containers can use the instance role for SES.
- Database is a **separate database + role on the shared instance**.

## Run

```bash
cd infra/aws
tofu init
tofu plan          # expect: 11 to add, 0 to change, 0 to destroy
tofu apply         # creates billable resources (~$20/mo) — only when you mean it
```

## Letting plynth reach the shared RDS  (REQUIRED, and easy to get wrong)

The RDS security group is owned by **Mayva's** stack, which declares its
`ingress` **inline** — that is authoritative. A rule added by hand or from this
stack is **deleted on Mayva's next `tofu apply`**, silently cutting plynth off
its database. So:

1. Make it durable first. The change is ready for review on the `mayva-desk`
   branch `chore/infra-extra-db-client-sgs`: an empty-by-default
   `extra_db_client_sg_ids` list rendered as `dynamic "ingress"` blocks on
   `aws_security_group.rds`. Merge it, then set
   `extra_db_client_sg_ids = ["<app_security_group_id output>"]` in their
   `terraform.tfvars` and apply with `-target=aws_security_group.rds` after
   confirming the plan is exactly one new ingress rule, `0 to destroy`.
   (A baseline plan of their stack also shows an in-place `aws_instance.app`
   `ami (sensitive value)` update — the known marking-only diff noted in their
   PROGRESS.md; `-target` keeps the apply off the production box entirely.)
2. Until that is merged, a temporary CLI rule works but WILL be reverted by
   their next apply — do not rely on it past cutover:
   `aws ec2 authorize-security-group-ingress --group-id <rds sg> --protocol tcp --port 5432 --source-group <plynth app sg>`

## Create the plynth database + role (by hand, on the box)

Kept out of Terraform so the password never lands in state. After `apply` and the
rule above, via `tofu output -raw ssm_session_command`:

```bash
PGPASS=$(openssl rand -base64 24 | tr -d '/+=')          # save in your password manager
docker run --rm -e PGPASSWORD='<RDS master password>' postgres:16-alpine \
  psql "host=<rds_endpoint> user=mayva dbname=postgres sslmode=require" \
  -c "CREATE ROLE platform LOGIN PASSWORD '$PGPASS'" \
  -c "CREATE DATABASE platform OWNER platform"
# DATABASE_URL=postgresql+asyncpg://platform:$PGPASS@<rds_endpoint>:5432/platform?ssl=require
```
Take a **manual RDS snapshot first** (it also holds Mayva's health data).

## Secrets that must carry over UNCHANGED from the droplet `.env`

`JWT_SECRET` (else every session is invalidated) and the **vault encryption key**
(else stored env-vault entries become unreadable forever), plus Razorpay keys and
webhook secret. Rotate separately: `PLATFORM_ADMIN_TOKEN`.

## Box first-time setup + deploys

Files (repo root): `docker-compose.aws.yml`, `Caddyfile.aws`,
`.github/workflows/deploy-aws.yml`. The workflow ships both config files to the
box itself, so the box needs **no git checkout** — only:

1. `/opt/plynth/.env` — hand-created over SSM, `chmod 600`, never committed. Keys
   are listed in the repo's `.env.example`. Values that matter:
   `DATABASE_URL` (see DB section), `REDIS_URL=redis://redis:6379/0`,
   `APP_ENV=production`, `JWT_SECRET` and the vault encryption key
   (**copied unchanged from the droplet**), `BILLING_PROVIDER=razorpay` + keys +
   webhook secret, `EMAIL_PROVIDER=ses` + `EMAIL_FROM_ADDRESS` (no AWS keys —
   the instance role supplies credentials), a **new** `PLATFORM_ADMIN_TOKEN`.
2. GitHub repo settings (one-time): variable `AWS_DEPLOY_ROLE_ARN`
   (`tofu output github_deploy_role_arn`) and variable `API_HOSTNAMES`
   (comma or space separated — start with the rehearsal host only).

Deploy flow (push to `main` after CI, or **Actions → Deploy (AWS) → Run
workflow**): build arm64 image on a native runner → push to ECR as the git SHA →
SSM: write config, pull, **run migrations with the new image while the old
containers still serve**, switch, health-check, and **auto-roll-back to the
previous image if unhealthy**. A failed migration aborts before anything is
replaced. The workflow is inert until `AWS_DEPLOY_ROLE_ARN` is set.

Rollback / redeploy an older build: run the workflow with `image_tag` = an
existing git SHA — it is already in ECR, so it is deployed without rebuilding.

Note: migrations here are the idempotent `scripts/migrate.py` runner (no down
migrations), so an image rollback does not undo schema changes — they are additive.

## Not in this stack (follow-ups)
- SES: verify the sender domain + request production access (account is in sandbox)
- The monthly budget lives in Mayva's stack ($50); ~$59/mo expected with this — raise it
- Migration rehearsal on a temporary hostname, then the DNS cutover (do **not**
  repoint the real API hostname until the rehearsal passes)
- Docs: `docs/deploy-digitalocean.md` and the architecture doc still describe the
  droplet; update them (and retire the droplet notes) after cutover
