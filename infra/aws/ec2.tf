resource "aws_instance" "app" {
  ami                    = var.app_ami
  instance_type          = var.app_instance_type
  subnet_id              = data.aws_subnets.rds_az.ids[0]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name
  user_data              = file("${path.module}/user_data.sh")

  # No key pair on purpose: access is SSM Session Manager only.

  # IMDSv2 only. Hop limit 2 so containers (one extra network hop) can fetch
  # the instance-role credentials boto3 needs for SES.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.app_root_gb
    encrypted   = true
  }

  disable_api_termination = true

  tags = { Name = "${var.project}-app" }

  lifecycle {
    # The box holds /opt/plynth/.env (JWT secret, vault encryption key, API
    # keys). A moved AMI or edited bootstrap script must NEVER replace it as a
    # side effect of an unrelated apply — that is how Mayva nearly lost theirs.
    ignore_changes = [ami, user_data]
  }
}

resource "aws_eip" "app" {
  domain   = "vpc"
  instance = aws_instance.app.id
  tags     = { Name = "${var.project}-app" }
}
