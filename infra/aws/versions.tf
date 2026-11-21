terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # STATE: local for the first run. State here holds no DB password (the DB
  # role is created by hand on the box, see README) but does hold resource ids,
  # so move it to an encrypted S3 backend before a second person touches this:
  #   backend "s3" { bucket = "...", key = "plynth/terraform.tfstate", region = "ap-south-1", encrypt = true }
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
