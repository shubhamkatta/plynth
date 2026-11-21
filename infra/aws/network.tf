# App box security group. NO SSH: shell access is SSM Session Manager, deploys
# are SSM Run Command. Only web traffic comes in.
resource "aws_security_group" "app" {
  name_prefix = "${var.project}-app-"
  description = "plynth app box: HTTP/HTTPS from anywhere, no SSH (use SSM)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP (Caddy ACME + redirect)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-app" }

  lifecycle {
    create_before_destroy = true
  }
}

# NOTE — deliberately NOT here: the rule letting this SG reach Postgres.
# The RDS security group belongs to Acme's stack, which declares its ingress
# INLINE (authoritative). Any rule added from this stack — or by hand — is
# deleted by Acme's next `tofu apply`, silently cutting plynth off its DB.
# The durable fix is a 6-line change in Acme's infra/aws/main.tf; see
# README § "Letting plynth reach the shared RDS".
