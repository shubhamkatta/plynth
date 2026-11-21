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
  # stack safely. Shares the bucket with the mayva-desk stack under a separate
  # key. `use_lockfile` is S3-native locking (OpenTofu >= 1.10), no DynamoDB.
  backend "s3" {
    bucket       = "mayva-tfstate"
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
