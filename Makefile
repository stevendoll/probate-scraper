SHELL := /bin/bash
ACCOUNT_ID   := 600775874112
REGION       := us-east-1
ECR_REPO     := probate-scraper/scraper
ECR_URI      := $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com/$(ECR_REPO)
STACK_NAME   := probate-scraper-collin-tx

.PHONY: help ecr-create ecr-login build push build-push sam-build deploy \
        run-task logs-scraper logs-api get-api-key invoke-trigger invoke-api \
        vpc-info local-db-start local-db-stop local-db-seed local-db-shell \
        local-api-start test

LOCAL_DYNAMO_URL := http://localhost:8000
LOCAL_ENV        := AWS_ENDPOINT_URL=$(LOCAL_DYNAMO_URL) AWS_DEFAULT_REGION=us-east-1 \
                    AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local \
                    DYNAMO_TABLE_NAME=leads \
                    LOCATIONS_TABLE_NAME=locations \
                    SUBSCRIBERS_TABLE_NAME=subscribers

help:
	@echo ""
	@echo "  Probate Scraper — make targets"
	@echo ""
	@echo "  Local development:"
	@echo "    local-db-start   Start DynamoDB Local (Docker)"
	@echo "    local-db-stop    Stop DynamoDB Local"
	@echo "    local-db-seed    Create tables + load CSV data + seed locations"
	@echo "    local-db-shell   Scan leads table (quick sanity check)"
	@echo "    local-api-start  Start API server locally (no Docker)"
	@echo "    test             Run unit tests"
	@echo ""
	@echo "  Setup (one-time):"
	@echo "    ecr-create       Create the ECR repository"
	@echo "    ecr-login        Authenticate Docker to ECR"
	@echo "    vpc-info         Print default VPC + subnet IDs (fill into samconfig.toml)"
	@echo ""
	@echo "  Build & Deploy:"
	@echo "    build            Build the scraper Docker image"
	@echo "    push             Push the image to ECR"
	@echo "    build-push       build + push"
	@echo "    sam-build        Package Lambda functions (sam build)"
	@echo "    deploy           sam build + sam deploy"
	@echo ""
	@echo "  Operate:"
	@echo "    run-task         Manually trigger a Fargate scrape task"
	@echo "    logs-scraper     Tail /ecs/probate-scraper CloudWatch logs"
	@echo "    logs-api         Tail ApiFunction Lambda logs"
	@echo "    get-api-key      Print the API Gateway key value"
	@echo "    invoke-trigger   Invoke POST /{location_path}/update locally via sam local"
	@echo "    invoke-api       Invoke GET /{location_path}/leads locally via sam local"
	@echo ""

# ── One-time setup ──────────────────────────────────────────────────────────

ecr-create:
	aws ecr create-repository \
		--repository-name $(ECR_REPO) \
		--region $(REGION) \
		--image-scanning-configuration scanOnPush=true

ecr-login:
	aws ecr get-login-password --region $(REGION) \
		| docker login --username AWS --password-stdin \
		  $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com

vpc-info:
	@echo "=== Default VPC ==="
	@aws ec2 describe-vpcs \
		--filters Name=is-default,Values=true \
		--query 'Vpcs[0].VpcId' --output text
	@echo "=== Public Subnets ==="
	@VPC=$$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
		--query 'Vpcs[0].VpcId' --output text); \
	aws ec2 describe-subnets \
		--filters Name=vpc-id,Values=$$VPC \
		--query 'Subnets[*].[SubnetId,AvailabilityZone]' \
		--output table

# ── Docker ──────────────────────────────────────────────────────────────────

build:
	docker build -t $(ECR_REPO):latest src/scraper/

push:
	docker tag $(ECR_REPO):latest $(ECR_URI):latest
	docker push $(ECR_URI):latest

build-push: build push

# ── SAM ─────────────────────────────────────────────────────────────────────

sam-build:
	sam build

deploy: sam-build
	sam deploy

# ── Operations ──────────────────────────────────────────────────────────────

run-task:
	@CLUSTER=$$(aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) \
		--query 'Stacks[0].Outputs[?OutputKey==`EcsClusterName`].OutputValue' \
		--output text); \
	TASK_DEF=$$(aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) \
		--query 'Stacks[0].Outputs[?OutputKey==`TaskDefinitionArn`].OutputValue' \
		--output text); \
	SUBNETS=$$(grep SubnetIds samconfig.toml | grep -oP 'subnet-[a-z0-9,]+'); \
	SG=$$(aws ec2 describe-security-groups \
		--filters Name=group-name,Values=probate-scraper-* \
		--query 'SecurityGroups[0].GroupId' --output text); \
	aws ecs run-task \
		--cluster $$CLUSTER \
		--task-definition $$TASK_DEF \
		--launch-type FARGATE \
		--network-configuration "awsvpcConfiguration={subnets=[$$SUBNETS],securityGroups=[$$SG],assignPublicIp=ENABLED}" \
		--overrides '{"containerOverrides":[{"name":"scraper","environment":[{"name":"SCRAPE_RUN_ID","value":"manual-$(shell date +%Y%m%dT%H%M%S)"}]}]}'

logs-scraper:
	aws logs tail /ecs/probate-scraper --follow --region $(REGION)

logs-api:
	sam logs -n ApiFunction --stack-name $(STACK_NAME) --tail

get-api-key:
	@KEY_ID=$$(aws apigateway get-api-keys \
		--name-query "probate-leads-api" \
		--include-values \
		--query 'items[0].id' \
		--output text); \
	aws apigateway get-api-key --api-key $$KEY_ID --include-value \
		--query 'value' --output text

invoke-trigger:
	sam local invoke TriggerFunction \
		-e tests/events/post-update.json \
		--env-vars env.local.json

invoke-api:
	sam local invoke ApiFunction \
		-e tests/events/get-leads.json \
		--env-vars env.local.json

local-api-start:
	pipenv run python scripts/local_api_server.py

test:
	pipenv run python -m unittest discover -s tests -p "test_*.py" -v

# ── Local DynamoDB ───────────────────────────────────────────────────────────

local-db-start:
	docker compose up -d dynamodb-local
	@echo "DynamoDB Local running at $(LOCAL_DYNAMO_URL)"

local-db-stop:
	docker compose down

local-db-seed:
	$(LOCAL_ENV) pipenv run python3 scripts/seed_local.py

local-db-shell:
	$(LOCAL_ENV) aws dynamodb scan \
		--table-name leads \
		--endpoint-url $(LOCAL_DYNAMO_URL) \
		--select COUNT
