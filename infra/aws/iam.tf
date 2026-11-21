# ---------------------------------------------------------------------------
# EC2 instance role: SSM-managed, pulls from ECR, sends mail via SES.
# No static AWS keys anywhere — containers get role credentials from IMDS
# (hop limit 2 in ec2.tf so boto3 inside Docker can reach it).
# ---------------------------------------------------------------------------
resource "aws_iam_role" "app" {
  name_prefix = "${var.project}-app-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "app_ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "app" {
  name_prefix = "app-"
  role        = aws_iam_role.app.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "EcrPull"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
        ]
        Resource = aws_ecr_repository.plynth.arn
      },
      {
        # Only as the configured sender, so a compromised box can't spoof
        # arbitrary From addresses.
        Sid      = "SesSend"
        Effect   = "Allow"
        Action   = ["ses:SendEmail", "ses:SendRawEmail"]
        Resource = "*"
        Condition = {
          StringEquals = { "ses:FromAddress" = var.ses_from_address }
        }
      },
    ]
  })
}

resource "aws_iam_instance_profile" "app" {
  name_prefix = "${var.project}-app-"
  role        = aws_iam_role.app.name
}

# ---------------------------------------------------------------------------
# GitHub Actions deploy role (OIDC; no stored keys). Trust is limited to ONE
# repo on ONE branch. Permissions: push to this ECR repo, and run the deploy
# command on THIS instance only.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "github_deploy" {
  name_prefix = "${var.project}-gh-deploy-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:ref:refs/heads/${var.deploy_branch}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  name_prefix = "deploy-"
  role        = aws_iam_role.github_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "EcrPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:DescribeImages", # the workflow skips the build when the SHA is already in ECR (redeploy / rollback)
        ]
        Resource = aws_ecr_repository.plynth.arn
      },
      {
        Sid      = "FindInstance"
        Effect   = "Allow"
        Action   = ["ec2:DescribeInstances"]
        Resource = "*"
      },
      {
        Sid    = "SendDeployCommand"
        Effect = "Allow"
        Action = ["ssm:SendCommand"]
        Resource = [
          aws_instance.app.arn,
          "arn:aws:ssm:${data.aws_region.current.name}::document/AWS-RunShellScript",
        ]
      },
      {
        Sid      = "ReadCommandResult"
        Effect   = "Allow"
        Action   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations", "ssm:ListCommands"]
        Resource = "*"
      },
    ]
  })
}
