# flask-cicd-pipeline

A production-style CI/CD pipeline that automatically builds, pushes, and deploys a containerized Flask application to AWS ECS Fargate via GitHub Actions — triggered on every push to `main`.

**Live endpoint:** `http://flask-cicd-alb-1090080014.us-east-2.elb.amazonaws.com`

---

## Architecture

```
GitHub Push → GitHub Actions → Docker Build (linux/amd64)
    → Amazon ECR → ECS Fargate (Task Definition Update)
        → Application Load Balancer → Public HTTP Endpoint
```

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   GitHub    │────▶│  GitHub Actions  │────▶│   Amazon ECR    │
│  (main)     │     │  (deploy.yml)    │     │  (Docker Image) │
└─────────────┘     └──────────────────┘     └────────┬────────┘
                            │                          │
                     OIDC Auth via                     ▼
                     IAM Role              ┌─────────────────────┐
                            │              │   ECS Fargate Task   │
                            └─────────────▶│   flask-cicd-task   │
                                           └──────────┬──────────┘
                                                      │
                                           ┌──────────▼──────────┐
                                           │  Application Load    │
                                           │  Balancer (ALB)     │
                                           │  HTTP:80 → Port 5000│
                                           └─────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Application | Python 3.11 · Flask 3.0 · Gunicorn |
| Containerization | Docker (`linux/amd64`) |
| Container Registry | Amazon ECR |
| Compute | AWS ECS Fargate (Serverless) |
| Load Balancing | AWS Application Load Balancer (ALB) |
| CI/CD | GitHub Actions |
| Authentication | OIDC (OpenID Connect) — keyless, no static credentials |
| IAM | Custom IAM Role with least-privilege inline policies |
| Region | `us-east-2` (Ohio) |

---

## Project Structure

```
flask-cicd-pipeline/
├── app/
│   └── app.py                    # Flask application
├── .github/
│   └── workflows/
│       └── deploy.yml            # GitHub Actions CI/CD workflow
├── Dockerfile                    # Container definition (linux/amd64)
├── requirements.txt              # Python dependencies
└── README.md
```

---

## Flask Application

The app exposes two routes:

```python
GET /        → {"message": "Flask CI/CD Pipeline", "status": "healthy", "version": "1.1.0"}
GET /health  → {"status": "healthy"}  # Used as ALB health check path
```

The `/health` endpoint is registered as the ALB target group health check path, confirming the container is live before traffic is routed to it.

---

## CI/CD Pipeline (GitHub Actions)

The workflow in `.github/workflows/deploy.yml` runs automatically on every push to `main` and executes the following steps:

1. **Checkout Code** — pulls the latest commit
2. **Configure AWS Credentials via OIDC** — assumes an IAM role using a short-lived JWT token (no stored AWS keys)
3. **Login to Amazon ECR** — authenticates Docker to the private registry
4. **Build, Tag & Push Image** — builds a `linux/amd64` Docker image tagged with the Git commit SHA and pushes to ECR
5. **Download Active Task Definition** — fetches the current ECS task definition JSON from AWS
6. **Render New Task Definition** — injects the new ECR image URI into the task definition
7. **Deploy to ECS** — registers the new task definition revision and updates the Fargate service, waiting for stability

```yaml
# Key environment variables in deploy.yml
AWS_REGION: us-east-2
ECR_REPOSITORY: flask-cicd-pipeline
ECS_CLUSTER: flask-cicd-cluster
ECS_SERVICE: flask-cicd-task-service
ECS_TASK_DEFINITION: flask-cicd-task
CONTAINER_NAME: flask-app
```

---

## AWS Infrastructure

All infrastructure was provisioned manually via the AWS Console. Terraform conversion is planned for Phase 4.

### ECR
- Private repository: `flask-cicd-pipeline`
- Stores versioned Docker images tagged by Git commit SHA

### ECS Fargate
- Cluster: `flask-cicd-cluster`
- Task Definition: `flask-cicd-task` (0.5 vCPU / 1 GB RAM, Linux/X86_64)
- Service: `flask-cicd-task-service` (Replica strategy, 1 desired task)
- Platform: Fargate LATEST, Public IP enabled

### Application Load Balancer
- Name: `flask-cicd-alb` (Internet-facing, IPv4)
- Listener: HTTP:80
- Target Group: `flask-cicd-tg` (IP type, HTTP:5000, health check path `/health`)

### Security Groups
| Group | Purpose | Inbound Rules |
|---|---|---|
| `flask-alb-sg` | ALB — public internet access | HTTP:80 from `0.0.0.0/0` |
| `default` | ECS Tasks — container access | TCP:5000 from `flask-alb-sg` |

The ALB and ECS tasks use **separate security groups** — a production best practice. The ALB accepts public traffic on port 80 and forwards it to containers on port 5000, with the ECS security group only trusting traffic originating from the ALB's security group.

### IAM — OIDC Authentication
Rather than using long-lived AWS access keys, this pipeline uses **GitHub OIDC** to authenticate:

1. An OIDC Identity Provider is configured in AWS IAM, pointing to `token.actions.githubusercontent.com`
2. A custom IAM role (`github-actions-ecs-deploy-role`) is assumed by the workflow at runtime
3. The role is scoped to this specific GitHub repository via a trust policy condition
4. Attached policies: `AmazonEC2ContainerRegistryPowerUser`, `AmazonECS_FullAccess`, and a custom inline `iam:PassRole` policy

This means **zero static credentials** are stored in GitHub Secrets.

---

## Local Development

### Prerequisites
- Docker Desktop
- Python 3.11+
- AWS CLI configured

### Run Locally

```bash
# Clone the repo
git clone https://github.com/MaxCadet/flask-cicd-pipeline.git
cd flask-cicd-pipeline

# Build the image (use linux/amd64 for Fargate compatibility)
docker build --platform linux/amd64 -t flask-cicd-pipeline .

# Run on port 5001 (avoids macOS AirPlay conflict on 5000)
docker run -p 5001:5000 flask-cicd-pipeline

# Test
curl http://localhost:5001
curl http://localhost:5001/health
```

### Push to ECR Manually

```bash
# Authenticate
aws ecr get-login-password --region us-east-2 | \
  docker login --username AWS --password-stdin \
  166665178530.dkr.ecr.us-east-2.amazonaws.com

# Tag and push
docker tag flask-cicd-pipeline:latest \
  166665178530.dkr.ecr.us-east-2.amazonaws.com/flask-cicd-pipeline:latest

docker push \
  166665178530.dkr.ecr.us-east-2.amazonaws.com/flask-cicd-pipeline:latest
```

---

## Deployment

To trigger a deployment, simply push to `main`:

```bash
git add .
git commit -m "your commit message"
git push origin main
```

GitHub Actions will automatically build, push, and deploy the new version to ECS Fargate. The pipeline waits for service stability before marking the run as successful.

---

## Troubleshooting Log

Real issues encountered and resolved during this build — the kind of hands-on debugging that only comes from building in production:

| Issue | Root Cause | Fix |
|---|---|---|
| `CannotPullContainerError` | Apple Silicon built `arm64` image; Fargate needs `amd64` | Added `--platform linux/amd64` to Docker build command |
| ALB timeout (ERR_TIMED_OUT) | ALB and ECS tasks shared same security group, creating a self-reference loop | Created dedicated `flask-alb-sg` and separated ALB/ECS security groups |
| `504 Gateway Timeout` | ECS security group not allowing inbound from ALB | Added port 5000 inbound rule sourced from `flask-alb-sg` |
| OIDC auth failure | `rn:aws:iam` typo — missing leading `a` in Role ARN | Corrected ARN string in `deploy.yml` |
| `iam:PassRole` denied | GitHub Actions role lacked permission to pass `ecsTaskExecutionRole` | Added inline `iam:PassRole` policy to the GitHub IAM role |
| ECS service MISSING | `ECS_CLUSTSER` typo in `deploy.yml` env vars block | Fixed variable name spelling to `ECS_CLUSTER` |
| `nothing to commit` on push | File saved after commit ran, so Git saw no changes | Used `Cmd+S` explicitly before staging and committing |
| Workflow file not detected | Workflow file created as `depoly.yml` instead of `deploy.yml` | Renamed with `mv` and re-pushed |
| PAT push rejected | Personal Access Token missing `workflow` scope | Updated PAT scope in GitHub Developer Settings |

---

## Roadmap

- [x] Phase 1 — Flask app built, Dockerized, running locally
- [x] Phase 2 — ECR repo, ECS Fargate cluster, ALB, public endpoint live
- [x] Phase 3 — GitHub Actions CI/CD with OIDC, automated deployments on push
- [ ] Phase 4 — Terraform IaC conversion of all AWS resources
- [ ] Phase 5 — Datadog observability integration (CloudWatch + Datadog agent)

---

## Author

**Max Cadet** — Cloud Engineering / DevOps  
AWS Certified Cloud Practitioner · Pursuing SAA-C03  
[GitHub](https://github.com/MaxCadet) · [LinkedIn](https://linkedin.com/in/maxcadet98) · [Email](mailto:cadetm98@gmail.com)
