.PHONY: build deploy clean test validate sync logs install help check-config setup-github-oidc

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install AWS SAM CLI and dependencies
	pip install aws-sam-cli pytest boto3

build: ## Build SAM application
	sam build

validate: ## Validate SAM template
	sam validate --lint

deploy: build ## Build and deploy to default environment
	sam deploy

deploy-dev: build ## Deploy to development environment
	sam deploy --config-env default

deploy-test: build ## Deploy to test environment
	sam deploy --config-env test

deploy-prod: build ## Deploy to production environment (with confirmation)
	@echo "WARNING: Deploying to PRODUCTION!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		sam deploy --config-env prod; \
	fi

local-api: build ## Start API locally
	sam local start-api

sync: ## Sync changes to AWS (fast iteration)
	sam sync --watch

test: ## Run unit tests
	pytest tests/ -v

test-coverage: ## Run tests with coverage report
	pytest tests/ --cov=src --cov-report=html --cov-report=term

logs: ## Tail logs for all functions (or specific: make logs FUNCTION=GetActiveTourFunction)
ifdef FUNCTION
	sam logs -n $(FUNCTION) --tail
else
	sam logs --tail
endif

logs-function: ## Tail logs for specific function (usage: make logs-function FUNCTION=GetActiveTourFunction)
	sam logs -n $(FUNCTION) --tail

logs-tail: ## Alias for logs-function (usage: make logs-tail FUNCTION=CreateCheckinFunction)
	sam logs -n $(FUNCTION) --tail

clean: ## Clean build artifacts
	rm -rf .aws-sam

delete: ## Delete CloudFormation stack
	@echo "WARNING: This will delete the entire stack!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		sam delete; \
	fi

invoke: ## Invoke a function locally (usage: make invoke FUNCTION=GetActiveTourFunction EVENT=events/test.json)
	sam local invoke $(FUNCTION) -e $(EVENT)

package: build ## Package application for deployment
	sam package --output-template-file packaged.yaml

lint: ## Lint Python code
	find src -name "*.py" -not -path "*/\.*" | xargs pylint

format: ## Format Python code
	find src -name "*.py" -not -path "*/\.*" | xargs black

provision-tour: ## Provision a new tour (usage: make provision-tour TOUR_ID=India-Coast-2026 TOUR_NAME="India Coastal Ride 2026" START_DATE=2026-02-10 END_DATE=2026-02-17)
	@if [ -z "$(TOUR_ID)" ] || [ -z "$(TOUR_NAME)" ] || [ -z "$(START_DATE)" ] || [ -z "$(END_DATE)" ]; then \
		echo "Usage: make provision-tour TOUR_ID=<id> TOUR_NAME=\"<name>\" START_DATE=YYYY-MM-DD END_DATE=YYYY-MM-DD [STACK_NAME=tour-data-api] [ENV=dev] [DESCRIPTION=\"...\"]"; \
		exit 1; \
	fi
	python scripts/provision_tour.py \
		--stack-name $(or $(STACK_NAME),tour-data-api) \
		--tour-id $(TOUR_ID) \
		--name "$(TOUR_NAME)" \
		--start-date $(START_DATE) \
		--end-date $(END_DATE) \
		--environment $(or $(ENV),dev) \
		$(if $(DESCRIPTION),--description "$(DESCRIPTION)",) \
		$(if $(SUBSCRIPTION_ID),--subscription-id $(SUBSCRIPTION_ID),)

all: validate build test deploy ## Run full pipeline: validate, build, test, deploy

check-config: ## Run preflight checks before deployment
	@bash scripts/preflight-check.sh

dev-test-setup: ## Export env vars for dev API testing (use with: source <(make dev-test-setup))
	@bash scripts/dev-test-setup.sh

setup-github-oidc: ## Set up GitHub OIDC for keyless deployments (one-time)
	@echo "Setting up GitHub OIDC for passwordless deployments..."
	@echo ""
	@read -p "GitHub username or org: " ORG; \
	read -p "GitHub repo name [tour-data-api]: " REPO; \
	REPO=$${REPO:-tour-data-api}; \
	aws cloudformation deploy \
		--template-file cloudformation/github-oidc.yaml \
		--stack-name tour-data-api-github-oidc \
		--capabilities CAPABILITY_NAMED_IAM \
		--parameter-overrides GitHubOrg=$$ORG GitHubRepo=$$REPO \
		--tags Project=tour-data-api ManagedBy=CloudFormation; \
	echo ""; \
	echo "=== Setup Complete ==="; \
	echo ""; \
	echo "Add this as AWS_DEPLOY_ROLE_ARN in your GitHub repository secrets:"; \
	aws cloudformation describe-stacks \
		--stack-name tour-data-api-github-oidc \
		--query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" \
		--output text; \
	echo ""
