terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # STATE: encrypted, versioned S3 — not a laptop. This state holds no DB
  # password (the DB role is created by hand on the box, see README) but does
  # hold every resource id, and losing it means losing the ability to plan this
  # stack safely. `use_lockfile` is S3-native locking (OpenTofu >= 1.10), no
  # DynamoDB.
  #
  # PARTIAL CONFIGURATION, deliberately: `bucket` is an account-specific name,
  # so it is supplied at init time rather than committed —
  #
  #     tofu init -backend-config=backend.hcl
  #
  # with a gitignored `backend.hcl` holding `bucket = "<your-state-bucket>"`.
  # A backend block cannot interpolate variables, so this is the only way to
  # keep the name out of the repo. Changing the bucket name here instead would
  # point the stack at an empty state and make `plan` propose creating every
  # resource that already exists.
  backend "s3" {
    key          = "plynth/terraform.tfstate"
    region       = "ap-south-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "opentofu"
      Stack     = "plynth-platform"
    }
  }
}
