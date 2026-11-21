output "app_public_ip" {
  description = "Elastic IP of the plynth box. Point the API hostname's A record here AT CUTOVER (not before)."
  value       = aws_eip.app.public_ip
}

output "instance_id" {
  value = aws_instance.app.id
}

output "app_security_group_id" {
  description = "Needed for the RDS ingress rule in Acme's stack (README)."
  value       = aws_security_group.app.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.plynth.repository_url
}

output "github_deploy_role_arn" {
  description = "Set as the plynth repo variable AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.github_deploy.arn
}

output "rds_endpoint" {
  description = "Shared RDS endpoint (from the data source)."
  value       = data.aws_db_instance.shared.address
}

output "ssm_session_command" {
  description = "Open a shell on the box (no SSH)."
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.app.id}"
}
