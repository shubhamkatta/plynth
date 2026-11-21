data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_vpc" "default" {
  default = true
}

# The shared database instance. Looked up, never managed, from this stack.
data "aws_db_instance" "shared" {
  db_instance_identifier = var.rds_identifier
}

# Put the app box in the SAME AZ as RDS: no cross-AZ data charges, lower latency.
data "aws_subnets" "rds_az" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "availability-zone"
    values = [data.aws_db_instance.shared.availability_zone]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

# The GitHub OIDC provider is account-global and already created by Acme's
# stack. Reuse it; creating a second one would fail.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}
