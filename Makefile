.PHONY: build deploy clean test validate sync logs install help check-config cleanup-tour-tables seed-app-config seed-notification-rules setup-notification-push

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

# Terminal deployments (dev iteration, ad hoc test) use the least-privilege terminal deploy role
# created by cloudformation/deploy-access.yaml: run with AWS_PROFILE=<terminal-role-profile>.
# Production is deployed from GitHub Actions only (main branch). See docs/guides/aws-deploy-access-setup.md.
deploy: deploy-dev ## Alias of deploy-dev

deploy-dev: build ## Build, deploy to dev and seed AppConfig/NotificationRule
	@ACCOUNT_ID=$$(aws sts get-caller-identity --query Account --output text) || exit 1; \
	sam deploy --config-env default --s3-bucket tour-data-api-sam-dev-$$ACCOUNT_ID || exit $$?; \
	$(MAKE) seed-app-config STACK_NAME=dev && $(MAKE) seed-notification-rules STACK_NAME=dev

deploy-test: build ## Build, deploy to test and seed AppConfig/NotificationRule
	@ACCOUNT_ID=$$(aws sts get-caller-identity --query Account --output text) || exit 1; \
	sam deploy --config-env test --s3-bucket tour-data-api-sam-test-$$ACCOUNT_ID || exit $$?; \
	$(MAKE) seed-app-config STACK_NAME=test && $(MAKE) seed-notification-rules STACK_NAME=test

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

delete: ## Delete stack and tour-specific tables (needs admin credentials; deploy roles cannot delete)
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

seed-app-config: ## Seed AppConfig table defaults (usage: make seed-app-config [STACK_NAME=dev] [REGION=ap-south-1])
	$(PYTHON) scripts/seed_app_config.py \
		--table-name $(or $(STACK_NAME),dev)-AppConfig \
		--region $(or $(REGION),ap-south-1)

seed-notification-rules: ## Seed NotificationRule table defaults
	$(PYTHON) scripts/seed_notification_rules.py \
		--table-name $(or $(STACK_NAME),dev)-NotificationRule \
		--region $(or $(REGION),ap-south-1)

setup-notification-push: ## Configure SSM Expo tokens and optional notification seeds
	$(PYTHON) scripts/setup_notification_push.py \
		--stack-name $(or $(STACK_NAME),dev) \
		--region $(or $(REGION),ap-south-1) \
		$(if $(RIDER_TOKEN),--rider-token "$(RIDER_TOKEN)",) \
		$(if $(MGMT_TOKEN),--mgmt-token "$(MGMT_TOKEN)",) \
		$(if $(OVERWRITE),--overwrite,) \
		$(if $(SEED_RULES),--seed-notification-rules,) \
		$(if $(SEED_APP_CONFIG),--seed-app-config,)

invoke: ## Invoke a function locally (usage: make invoke FUNCTION=GetActiveTourFunction EVENT=events/test.json)
	sam local invoke $(FUNCTION) -e $(EVENT)

package: build ## Package application for deployment
	sam package --output-template-file packaged.yaml

lint: ## Lint Python code
	find src -name "*.py" -not -path "*/\.*" | xargs $(PYTHON) -m pylint

format: ## Format Python code
	find src -name "*.py" -not -path "*/\.*" | xargs $(PYTHON) -m black

provision-tour: ## Provision a new tour (usage: make provision-tour TOUR_ID=TOT-2026 TOUR_NAME="Tour of Tamilnadu 2026" START_DATE=2026-02-10 END_DATE=2026-02-17 RIDE_COUNT=8)
	@if [ -z "$(TOUR_ID)" ] || [ -z "$(TOUR_NAME)" ] || [ -z "$(START_DATE)" ] || [ -z "$(END_DATE)" ] || [ -z "$(RIDE_COUNT)" ]; then \
		echo "Usage: make provision-tour TOUR_ID=<id> TOUR_NAME=\"<name>\" START_DATE=YYYY-MM-DD END_DATE=YYYY-MM-DD RIDE_COUNT=<n> [STACK_NAME=dev] [ENV=dev] [DESCRIPTION=\"...\"]"; \
		exit 1; \
	fi
	$(PYTHON) scripts/provision_tour.py \
		--stack-name $(or $(STACK_NAME),dev) \
		--tour-id $(TOUR_ID) \
		--name "$(TOUR_NAME)" \
		--start-date $(START_DATE) \
		--end-date $(END_DATE) \
		--ride-count $(RIDE_COUNT) \
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

all: validate build test deploy ## Run full pipeline: validate, build, test, deploy

check-config: ## Run preflight checks before deployment
	@bash scripts/preflight-check.sh

dev-test-setup: ## Export env vars for dev API testing (use with: source <(make dev-test-setup))
	@bash scripts/dev-test-setup.sh
