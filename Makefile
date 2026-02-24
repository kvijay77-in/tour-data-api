.PHONY: build deploy clean test validate sync logs install help check-config setup-github-oidc cleanup-tour-tables

# Auto-detect Python: prefer project venv, then system python3/python
# Project venv has the required dependencies (boto3, pytest, etc.)
ifneq (,$(wildcard .venv/bin/python))
  PYTHON := .venv/bin/python
else
  PYTHON := $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null)
  ifeq ($(PYTHON),)
    $(error No Python found. Create a virtual environment with 'python3 -m venv .venv' or install Python 3.11+)
  endif
endif
PIP := $(PYTHON) -m pip

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install AWS SAM CLI and dependencies
	$(PIP) install aws-sam-cli pytest boto3

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
	$(PYTHON) -m pytest tests/ -v

test-coverage: ## Run tests with coverage report
	$(PYTHON) -m pytest tests/ --cov=src --cov-report=html --cov-report=term

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

delete: ## Delete CloudFormation stack and tour-specific tables
	@echo "WARNING: This will delete the entire stack and all tour-specific DynamoDB tables!"
	@printf "Are you sure? [y/N] "; \
	read REPLY; \
	case "$$REPLY" in \
		[Yy]*) \
			echo ""; \
			echo "--- Cleaning up tour-specific tables ---"; \
			$(PYTHON) scripts/cleanup_tour_tables.py --stack-name $(or $(STACK_NAME),dev) --confirm; \
			echo ""; \
			echo "--- Deleting CloudFormation stack ---"; \
			sam delete; \
			;; \
		*) \
			echo "Aborted."; \
			;; \
	esac

cleanup-tour-tables: ## Delete tour-specific DynamoDB tables (dry run by default, use CONFIRM=true to delete)
	@if [ "$(CONFIRM)" = "true" ]; then \
		$(PYTHON) scripts/cleanup_tour_tables.py --stack-name $(or $(STACK_NAME),dev) --confirm; \
	else \
		$(PYTHON) scripts/cleanup_tour_tables.py --stack-name $(or $(STACK_NAME),dev); \
	fi

invoke: ## Invoke a function locally (usage: make invoke FUNCTION=GetActiveTourFunction EVENT=events/test.json)
	sam local invoke $(FUNCTION) -e $(EVENT)

package: build ## Package application for deployment
	sam package --output-template-file packaged.yaml

lint: ## Lint Python code
	find src -name "*.py" -not -path "*/\.*" | xargs $(PYTHON) -m pylint

format: ## Format Python code
	find src -name "*.py" -not -path "*/\.*" | xargs $(PYTHON) -m black

provision-tour: ## Provision a new tour (usage: make provision-tour TOUR_ID=TOT-2026 TOUR_NAME="Tour of Tamilnadu 2026" START_DATE=2026-02-10 END_DATE=2026-02-17)
	@if [ -z "$(TOUR_ID)" ] || [ -z "$(TOUR_NAME)" ] || [ -z "$(START_DATE)" ] || [ -z "$(END_DATE)" ]; then \
		echo "Usage: make provision-tour TOUR_ID=<id> TOUR_NAME=\"<name>\" START_DATE=YYYY-MM-DD END_DATE=YYYY-MM-DD [STACK_NAME=dev] [ENV=dev] [DESCRIPTION=\"...\"]"; \
		exit 1; \
	fi
	$(PYTHON) scripts/provision_tour.py \
		--stack-name $(or $(STACK_NAME),dev) \
		--tour-id $(TOUR_ID) \
		--name "$(TOUR_NAME)" \
		--start-date $(START_DATE) \
		--end-date $(END_DATE) \
		--environment $(or $(ENV),dev) \
		$(if $(DESCRIPTION),--description "$(DESCRIPTION)",) \
		$(if $(SUBSCRIPTION_ID),--subscription-id $(SUBSCRIPTION_ID),)

generate-test-data: ## Generate test data from scenario template (usage: make generate-test-data SCENARIO=scripts/test_data/scenario_tot_2026.yaml [STACK_NAME=dev] [SEED=42])
	@if [ -z "$(SCENARIO)" ]; then \
		echo "Usage: make generate-test-data SCENARIO=<path-to-yaml> [STACK_NAME=dev] [SEED=42] [DRY_RUN=true]"; \
		exit 1; \
	fi
	$(PYTHON) scripts/generate_test_data.py \
		--scenario $(SCENARIO) \
		--stack-name $(or $(STACK_NAME),dev) \
		$(if $(SEED),--seed $(SEED),) \
		$(if $(filter true,$(DRY_RUN)),--dry-run,) \
		$(if $(REGION),--region $(REGION),)

cleanup-test-data: ## Clean up test data from tour-specific tables (usage: make cleanup-test-data TOUR_ID=TOT-2026 [CONFIRM=true])
	@if [ -z "$(TOUR_ID)" ]; then \
		echo "Usage: make cleanup-test-data TOUR_ID=<id> [STACK_NAME=dev] [CONFIRM=true] [INCLUDE_PROFILES=true]"; \
		exit 1; \
	fi
	@if [ "$(CONFIRM)" = "true" ]; then \
		$(PYTHON) scripts/cleanup_test_data.py \
			--stack-name $(or $(STACK_NAME),dev) \
			--tour-id $(TOUR_ID) \
			$(if $(filter true,$(INCLUDE_PROFILES)),--include-profiles,) \
			$(if $(REGION),--region $(REGION),) \
			--confirm; \
	else \
		$(PYTHON) scripts/cleanup_test_data.py \
			--stack-name $(or $(STACK_NAME),dev) \
			--tour-id $(TOUR_ID) \
			$(if $(filter true,$(INCLUDE_PROFILES)),--include-profiles,) \
			$(if $(REGION),--region $(REGION),); \
	fi

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
