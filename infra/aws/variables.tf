variable "region" {
  description = "AWS region. Mumbai, matching Mayva's REGION=in data-residency rule."
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Name prefix for all resources."
  type        = string
  default     = "plynth"
}

# --- App box ---------------------------------------------------------------
variable "app_instance_type" {
  description = "EC2 type. t4g.small (2 vCPU, 2 GB, arm64) is the lean default."
  type        = string
  default     = "t4g.small"
}

variable "app_root_gb" {
  description = "Root EBS volume size (GB)."
  type        = number
  default     = 30
}

# PINNED on purpose. A "latest Ubuntu" lookup moves on Canonical's schedule and
# makes `plan` want to REPLACE the instance (Mayva hit exactly this and had to
# pin). The instance also ignores ami/user_data changes (see ec2.tf), so
# bumping this is a deliberate, reviewed act. Current value read 2026-11-21 from
#   aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id
variable "app_ami" {
  description = "Ubuntu 24.04 arm64 AMI for the app box. Pinned — see note above."
  type        = string
  default     = "ami-0625bef1ea02ae20c"
}

# --- Shared RDS (owned by Mayva's stack; looked up read-only) --------------
variable "rds_identifier" {
  description = "Identifier of the EXISTING RDS instance plynth shares (Mayva's)."
  type        = string
  default     = "mayva-db"
}

variable "db_name" {
  description = "Database created for plynth on the shared instance (by hand, see README)."
  type        = string
  default     = "platform"
}

variable "db_username" {
  description = "Role created for plynth on the shared instance (by hand, see README)."
  type        = string
  default     = "platform"
}

# --- GitHub Actions deploy (OIDC + SSM) ------------------------------------
variable "github_repo" {
  description = "owner/repo allowed to assume the deploy role."
  type        = string
  default     = "shubhamkatta/plynth"
}

variable "deploy_branch" {
  description = "Only workflows running on this branch may assume the deploy role."
  type        = string
  default     = "main"
}

# --- SES (email) -----------------------------------------------------------
variable "ses_from_address" {
  description = "Sender the app box may send as via SES (must be a verified identity)."
  type        = string
  default     = "no-reply@mayva.ai"
}

variable "api_hostname" {
  description = "Public hostname plynth serves (used in outputs/README; Caddy owns the cert)."
  type        = string
  default     = "api.corporatethings.com"
}
