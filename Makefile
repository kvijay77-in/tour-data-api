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

all: validate build test deploy ## Run full pipeline: validate, build, test, deploy

check-config: ## Run preflight checks before deployment
	@bash scripts/preflight-check.sh

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
