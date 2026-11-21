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

1. Make it durable first, in `mayva-desk/infra/aws/main.tf` (their repo, their
   review). Add a variable and a second ingress block to `aws_security_group.rds`:

   ```hcl
   variable "extra_db_client_sg_ids" {
     description = "SGs (other stacks, e.g. plynth) allowed to reach Postgres."
     type        = list(string)
     default     = []
   }
   # inside aws_security_group.rds:
   ingress {
     description     = "Postgres from other stacks' app boxes"
     from_port       = 5432
     to_port         = 5432
     protocol        = "tcp"
     security_groups = var.extra_db_client_sg_ids
   }
   ```
   then set `extra_db_client_sg_ids = ["<app_security_group_id output>"]` and apply
   **that** stack with a plan reviewed for `0 to destroy` (its plan previously
   wanted to replace the production box — the AMI pin fixed it; verify).
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

## Not in this stack (follow-ups)
- `docker-compose.aws.yml` (image from ECR, no db service) + Caddyfile
- GitHub Actions: build arm64 → ECR → SSM deploy (`AWS_DEPLOY_ROLE_ARN` repo var)
- SES: verify the sender domain + request production access (account is in sandbox)
- The monthly budget lives in Mayva's stack ($50); ~$59/mo expected with this — raise it
- DNS cutover for the API hostname (do **not** repoint until the rehearsal passes)
