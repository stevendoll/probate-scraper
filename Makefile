SHELL := /bin/bash
ACCOUNT_ID   := 600775874112
REGION       := us-east-1
ECR_REPO     := probate-scraper/scraper
ECR_URI      := $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com/$(ECR_REPO)
STACK_NAME        := probate-scraper
DOCUMENTS_BUCKET  ?= probate-scraper-documentsbucket-atqg0aimr8md

# UI deployment — resolved from CloudFormation Outputs after sam deploy
UI_BUCKET    = $(shell aws cloudformation describe-stacks \
                 --stack-name $(STACK_NAME) --region $(REGION) \
                 --query "Stacks[0].Outputs[?OutputKey==\`UiBucketName\`].OutputValue" \
                 --output text 2>/dev/null)
CF_DIST_ID   = $(shell aws cloudformation describe-stacks \
                 --stack-name $(STACK_NAME) --region $(REGION) \
                 --query "Stacks[0].Outputs[?OutputKey==\`UiDistributionId\`].OutputValue" \
                 --output text 2>/dev/null)

.PHONY: help ecr-create ecr-login build push build-push sam-build deploy deploy-ui \
        run-task logs-scraper logs-api get-api-key invoke-trigger invoke-api \
        vpc-info local-db-start local-db-stop local-db-seed local-db-reset local-db-shell \
        local-api-start local-scraper-run start-all test smoke-test check-bedrock \
        create-jwt-secret email-setup aws-db-reset seed-prod \
        backfill-s3-uris backfill-s3-uris-local

LOCAL_DYNAMO_URL := http://localhost:8000
LOCAL_ENV        := AWS_ENDPOINT_URL=$(LOCAL_DYNAMO_URL) AWS_DEFAULT_REGION=us-east-1 \
                    DOCUMENTS_TABLE_NAME=documents \
                    CONTACTS_TABLE_NAME=contacts \
                    PROPERTIES_TABLE_NAME=properties \
                    LOCATIONS_TABLE_NAME=locations \
                    FROM_EMAIL=hello@collincountyleads.com

# Scraper local-run defaults — override on the command line or via env:
#   SCRAPER_USERNAME=you@example.com SCRAPER_PASSWORD='p@ss' make local-scraper-run
LOCATION_CODE     ?= CollinTx
CHROMEDRIVER_PATH ?= /opt/homebrew/bin/chromedriver
CHROME_BIN        ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
SCRAPER_USERNAME  ?=
SCRAPER_PASSWORD  ?=
DOWNLOAD_DIR      ?= $(PWD)/downloads

help:
	@echo ""
	@echo "  Probate Scraper — make targets"
	@echo ""
	@echo "  Local development:"
	@echo "    start-all        Start database, API, and UI (in background)"
	@echo "    local-db-start   Start DynamoDB Local (Docker)"
	@echo "    local-db-stop    Stop DynamoDB Local"
	@echo "    local-db-seed    Create tables + load CSV data + seed locations"
	@echo "    local-db-shell   Scan documents table (quick sanity check)"
	@echo "    local-api-start  Start API server locally (no Docker)"
	@echo "    local-scraper-run  Run scraper against DynamoDB Local + upload PDFs to S3"
	@echo "                       SCRAPER_USERNAME=x SCRAPER_PASSWORD='y' make local-scraper-run"
	@echo "    backfill-s3-uris     Back-fill doc_s3_uri in AWS DynamoDB from S3 bucket"
	@echo "                         DOCUMENTS_BUCKET=<bucket> make backfill-s3-uris [DRY_RUN=1]"
	@echo "    backfill-s3-uris-local  Same but targets local DynamoDB"
	@echo "                         DOCUMENTS_BUCKET=<bucket> make backfill-s3-uris-local [DRY_RUN=1]"
	@echo "    test             Run unit tests"
	@echo "    smoke-test       Smoke test the deployed API (set SMOKE_BASE_URL + SMOKE_API_KEY)"
	@echo "    check-bedrock    Verify Bedrock model access before deploying ParseDocumentFunction"
	@echo "    email-setup      Configure email for local development"
	@echo "    aws-db-reset     Reset ALL production tables and seed initial data (DANGEROUS - requires confirmation)"
	@echo "    seed-prod        Create production tables and seed initial data"
	@echo ""
	@echo "  Setup (one-time):"
	@echo "    ecr-create       Create the ECR repository"
	@echo "    ecr-login        Authenticate Docker to ECR"
	@echo "    vpc-info         Print default VPC + subnet IDs (fill into samconfig.toml)"
	@echo "    create-jwt-secret  Generate random JWT secret → SSM /probate-scraper/jwt-secret"
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
	@echo "    invoke-api       Invoke GET /{location_path}/documents locally via sam local"
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
	@echo "Ensuring deploy IAM user has required permissions..."
	aws iam put-user-policy \
		--user-name probate-scraper-deploy \
		--policy-name CloudFrontDeploy \
		--policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"cloudfront:*","Resource":"*"}]}'
	aws iam put-user-policy \
		--user-name probate-scraper-deploy \
		--policy-name SsmSecretRead \
		--policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ssm:GetParameter","ssm:GetParameters"],"Resource":"arn:aws:ssm:$(REGION):$(ACCOUNT_ID):parameter/probate-scraper/*"}]}'
	@JWT_SECRET=$$(aws ssm get-parameter \
		--name /probate-scraper/jwt-secret \
		--with-decryption \
		--query Parameter.Value \
		--output text \
		--region $(REGION) 2>/dev/null); \
	if [ -z "$$JWT_SECRET" ]; then \
		echo "ERROR: SSM parameter /probate-scraper/jwt-secret not found. Run: make create-jwt-secret"; \
		exit 1; \
	fi; \
	if ! aws cloudformation describe-stacks --stack-name $(STACK_NAME) \
		--region $(REGION) >/dev/null 2>&1; then \
		echo "Stack does not exist — dropping any retained tables..."; \
		for TABLE in documents contacts properties events; do \
			if aws dynamodb describe-table --table-name $$TABLE \
				--region $(REGION) >/dev/null 2>&1; then \
				echo "Deleting table: $$TABLE"; \
				aws dynamodb delete-table --table-name $$TABLE --region $(REGION); \
				aws dynamodb wait table-not-exists --table-name $$TABLE --region $(REGION); \
			fi; \
		done; \
	fi; \
	sam deploy --parameter-overrides "JwtSecret=$$JWT_SECRET"
	$(MAKE) deploy-ui

deploy-ui:
	@echo "Building UI for production..."
	@KEY_ID=$$(aws cloudformation describe-stack-resources \
		--stack-name $(STACK_NAME) --region $(REGION) \
		--query 'StackResources[?ResourceType==`AWS::ApiGateway::ApiKey`].PhysicalResourceId | [0]' \
		--output text); \
	API_URL=$$(aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) --region $(REGION) \
		--query "Stacks[0].Outputs[?OutputKey==\`ApiEndpoint\`].OutputValue" \
		--output text); \
	API_KEY=$$(aws apigateway get-api-key --api-key $$KEY_ID --include-value \
		--query value --output text --region $(REGION)); \
	cd ui && VITE_API_URL=$$API_URL/real-estate/probate-leads VITE_API_KEY=$$API_KEY npm run build
	@echo "Syncing to s3://$(UI_BUCKET)..."
	aws s3 sync ui/dist/ s3://$(UI_BUCKET) --delete --region $(REGION)
	@echo "Invalidating CloudFront cache..."
	aws cloudfront create-invalidation --distribution-id $(CF_DIST_ID) --paths "/*"
	@echo "Done — https://$(CF_DIST_ID).cloudfront.net"


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
	@KEY_ID=$$(aws cloudformation describe-stack-resources \
		--stack-name $(STACK_NAME) \
		--region $(REGION) \
		--query 'StackResources[?ResourceType==`AWS::ApiGateway::ApiKey`].PhysicalResourceId | [0]' \
		--output text); \
	aws apigateway get-api-key --api-key $$KEY_ID --include-value \
		--query 'value' --output text --region $(REGION)

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

start-all:
	@echo "Starting database, API, and UI..."
	@if curl -s http://localhost:8000 > /dev/null 2>&1; then \
		echo "Database already running"; \
	else \
		$(MAKE) local-db-start; \
		echo "Waiting for database to be ready..."; \
		sleep 3; \
	fi
	@echo "Seeding database..."
	$(MAKE) local-db-seed
	@if pgrep -f "scripts/local_api_server.py" > /dev/null; then \
		echo "API server already running"; \
	else \
		echo "Starting API server..."; \
		$(MAKE) local-api-start & \
		API_PID=$$!; \
		echo "API PID: $$API_PID"; \
		sleep 5; \
	fi
	@if [ ! -f ui/.env.local ]; then \
		echo "Creating ui/.env.local from example (VITE_API_KEY=local)..."; \
		sed 's/your-api-key-here/local/' ui/.env.local.example > ui/.env.local; \
	fi
	@if curl -s http://localhost:3001 > /dev/null 2>&1; then \
		echo "UI already running"; \
	else \
		echo "Starting UI..."; \
		(cd ui && [ -d node_modules ] || npm install && npm run dev) & \
		UI_PID=$$!; \
		echo "UI PID: $$UI_PID"; \
	fi
	@echo ""; \
	echo "Services status:"; \
	echo "  - Database: $$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000 2>/dev/null || echo "NOT RUNNING")"; \
	echo "  - API: $$(pgrep -f "scripts/local_api_server.py" > /dev/null && echo "RUNNING" || echo "NOT RUNNING")"; \
	echo "  - UI: $$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3001 2>/dev/null || echo "NOT RUNNING")"; \
	echo ""; \
	echo "Access URLs:"; \
	echo "  - Database: http://localhost:8000"; \
	echo "  - API: http://localhost:3000"; \
	echo "  - UI: http://localhost:3001"; \
	echo ""; \
	echo "To stop all services:"; \
	echo "  - Database: make local-db-stop"; \
	echo "  - API/UI: pkill -f 'local_api_server.py\|vite --port 3001'"

local-scraper-run:
	@set -a; [ -f .env ] && source .env; set +a; \
	$(LOCAL_ENV) \
	LOCATION_CODE="$(LOCATION_CODE)" \
	CHROMEDRIVER_PATH="$(CHROMEDRIVER_PATH)" \
	CHROME_BIN="$(CHROME_BIN)" \
	DOWNLOAD_DIR="$(DOWNLOAD_DIR)" \
	DOCUMENTS_BUCKET="$${DOCUMENTS_BUCKET:-$(DOCUMENTS_BUCKET)}" \
	SCRAPER_USERNAME="$${SCRAPER_USERNAME:-$(SCRAPER_USERNAME)}" \
	SCRAPER_PASSWORD="$${SCRAPER_PASSWORD:-$(SCRAPER_PASSWORD)}" \
	pipenv run python src/scraper/app.py

test:
	pipenv run python -m unittest discover -s tests -p "test_*.py" -v

# Run smoke tests against the deployed API.
# Requires SMOKE_BASE_URL and SMOKE_API_KEY to be set:
#   export SMOKE_BASE_URL=$(aws cloudformation describe-stacks \
#     --stack-name probate-scraper \
#     --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
#     --output text)
#   export SMOKE_API_KEY=$(make get-api-key)
#   make smoke-test
smoke-test:
	pipenv run python scripts/smoke_test.py

# Verify the Bedrock model is accessible before deploying ParseDocumentFunction.
# Run once per account/region after initial AWS setup, or after changing BedrockModelId.
check-bedrock:
	pipenv run python scripts/check_bedrock.py

# Generate a random JWT secret and store it in SSM Parameter Store.
# Run once before first production deploy, or to rotate the secret.
create-jwt-secret:
	@SECRET=$$(python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(48)).decode())"); \
	aws ssm put-parameter \
		--name /probate-scraper/jwt-secret \
		--type SecureString \
		--value "$$SECRET" \
		--overwrite \
		--region $(REGION); \
	echo "JWT secret stored at /probate-scraper/jwt-secret"

# ── Local DynamoDB ───────────────────────────────────────────────────────────

local-db-start:
	docker compose up -d dynamodb-local
	@echo "DynamoDB Local running at $(LOCAL_DYNAMO_URL)"
local-db-stop:
	docker compose down

local-db-seed:
	$(LOCAL_ENV) pipenv run python3 scripts/seed_local.py

local-db-reset:
	@echo "    local-db-reset   Drop and recreate all tables in DynamoDB Local"
	-$(LOCAL_ENV) aws dynamodb delete-table --table-name documents \
		--endpoint-url $(LOCAL_DYNAMO_URL) > /dev/null 2>&1
	-$(LOCAL_ENV) aws dynamodb delete-table --table-name contacts \
		--endpoint-url $(LOCAL_DYNAMO_URL) > /dev/null 2>&1
	-$(LOCAL_ENV) aws dynamodb delete-table --table-name properties \
		--endpoint-url $(LOCAL_DYNAMO_URL) > /dev/null 2>&1
	-$(LOCAL_ENV) aws dynamodb delete-table --table-name locations \
		--endpoint-url $(LOCAL_DYNAMO_URL) > /dev/null 2>&1
	-$(LOCAL_ENV) aws dynamodb delete-table --table-name users \
		--endpoint-url $(LOCAL_DYNAMO_URL) > /dev/null 2>&1
	-$(LOCAL_ENV) aws dynamodb delete-table --table-name events \
		--endpoint-url $(LOCAL_DYNAMO_URL) > /dev/null 2>&1
	@sleep 2
	$(LOCAL_ENV) pipenv run python3 scripts/seed_local.py
	@echo "Reset complete."

aws-db-reset:
	@echo "Dropping and recreating all tables in production DynamoDB..."
	pipenv run python3 scripts/reset_production_db.py

seed-prod:
	@echo "Creating production tables and seeding initial data..."
	pipenv run python3 scripts/seed_production.py

local-db-shell:
	$(LOCAL_ENV) aws dynamodb scan \
		--table-name documents \
		--endpoint-url $(LOCAL_DYNAMO_URL) \
		--select COUNT

# ── Email Setup ─────────────────────────────────────────────────────────────

# ── S3 URI backfill ──────────────────────────────────────────────────────────
# Scan the S3 bucket and populate doc_s3_uri on documents that are missing it.
#
# DOCUMENTS_BUCKET=<bucket> make backfill-s3-uris          # live run (AWS DDB)
# DOCUMENTS_BUCKET=<bucket> make backfill-s3-uris DRY_RUN=1 # dry run
# DOCUMENTS_BUCKET=<bucket> make backfill-s3-uris-local    # live run (local DDB)

DRY_RUN ?=

backfill-s3-uris:
	@if [ -z "$(DOCUMENTS_BUCKET)" ]; then \
		echo "ERROR: DOCUMENTS_BUCKET is not set."; \
		echo "Usage: DOCUMENTS_BUCKET=<bucket> make backfill-s3-uris"; \
		exit 1; \
	fi
	DOCUMENTS_BUCKET="$(DOCUMENTS_BUCKET)" \
	pipenv run python scripts/backfill_s3_uris.py \
		$(if $(DRY_RUN),--dry-run,)

backfill-s3-uris-local:
	@if [ -z "$(DOCUMENTS_BUCKET)" ]; then \
		echo "ERROR: DOCUMENTS_BUCKET is not set."; \
		echo "Usage: DOCUMENTS_BUCKET=<bucket> make backfill-s3-uris-local"; \
		exit 1; \
	fi
	DOCUMENTS_BUCKET="$(DOCUMENTS_BUCKET)" \
	LOCAL_DYNAMO_URL="$(LOCAL_DYNAMO_URL)" \
	pipenv run python scripts/backfill_s3_uris_local.py \
		$(if $(DRY_RUN),--dry-run,)

# ── Email Setup ─────────────────────────────────────────────────────────────

email-setup:
	@echo "=== Email Configuration for Local Development ==="
	@echo ""
	@echo "Current AWS Identity:"
	@aws sts get-caller-identity --query 'Account' --output text | sed 's/^/  Account: /'
	@echo ""
	@echo "Verified SES Identities:"
	@aws ses list-identities --query 'Identities[]' --output text | sed 's/^/  - /'
	@echo ""
	@echo "Current FROM_EMAIL setting:"
	@if [ -z "$$FROM_EMAIL" ]; then \
		echo "  FROM_EMAIL is not set (emails will be logged to console)"; \
	else \
		echo "  FROM_EMAIL=$$FROM_EMAIL"; \
	fi
	@echo ""
	@echo "Default behavior: Emails are sent via SES using hello@collincountyleads.com"
	@echo ""
	@echo "To change email address:"
	@echo "  export FROM_EMAIL=\"your-verified-email@domain.com\""
	@echo "  make local-api-start"
	@echo ""
	@echo "To disable email sending (console logging only):"
	@echo "  export FROM_EMAIL=\"\""
	@echo "  make local-api-start"
