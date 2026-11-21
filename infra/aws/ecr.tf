# One image serves both the API and the worker (different `command`).
# Immutable tags: deploys reference a git SHA, never a moving `latest`.
resource "aws_ecr_repository" "plynth" {
  name                 = var.project
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "plynth" {
  repository = aws_ecr_repository.plynth.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 15 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 15
      }
      action = { type = "expire" }
    }]
  })
}
