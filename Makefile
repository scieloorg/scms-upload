default: build

export SCMS_BUILD_DATE=$(shell date -u +"%Y-%m-%dT%H:%M:%SZ")
export SCMS_VCS_REF=$(strip $(shell git rev-parse --short HEAD))
export SCMS_WEBAPP_VERSION=$(strip $(shell cat VERSION))

# This check if docker compose version
ifneq ($(shell docker compose version 2>/dev/null),)
  DOCKER_COMPOSE=docker compose
else
  DOCKER_COMPOSE=docker-compose
  DOCKER_COMPATIBILITY=--compatibility
endif

help: ## Show this help
	@echo 'Usage: make [target] [argument] ...'
	@echo ''
	@echo 'Argument:'
	@echo "\t compose = {compose_file_name}"
	@echo ''
	@echo 'Targets:'
	@egrep '^(.+)\:\ .*##\ (.+)' ${MAKEFILE_LIST} | sed 's/:.*##/#/' | column -t -c 1 -s "#"
	@echo ''
	@echo 'Example:'
	@echo "\t Type 'make' (default target=build) is the same of type 'make build compose=local.yml'"
	@echo "\t Type 'make build' is the same of type 'make build compose=local.yml'"
	@echo "\t Type 'make up' is the same of type 'make up compose=local.yml'"

app_version: ## Show version of webapp
	@echo "Version: " $(SCMS_WEBAPP_VERSION)

latest_commit:  ## Show last commit ref
	@echo "Latest commit: " $(SCMS_VCS_REF)

build_date: ## Show build date
	@echo "Build date: " $(SCMS_BUILD_DATE)

############################################
## atalhos docker-compose desenvolvimento ##
############################################

build:  ## Build app using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) build

build_no_cache:  ## Build app using $(compose) --no-cache
	$(DOCKER_COMPOSE) -f $(compose) build --no-cache

up:  ## Start app using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) up -d

up_scale:  ## Start app using $(compose) and scaling worker up to $(numworkers)
	$(eval numworkers ?= 1)
	$(DOCKER_COMPOSE) $(DOCKER_COMPATIBILITY) -f $(compose) up -d --scale celeryworker=$(numworkers)

logs: ## See all app logs using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) logs -f

stop:  ## Stop all app using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) stop

restart:
	$(DOCKER_COMPOSE) -f $(compose) restart
ps:  ## See all containers using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) ps

top:  ## See docker top using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) top

stats:  ## See docker stats using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) stats

rm:  ## Remove all containers using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) rm -f

pull_webapp: ## Pull Django image
	@echo "Pulling scms-upload version $(SCMS_WEBAPP_VERSION) ..."
	$(DOCKER_COMPOSE) -f $(compose) pull django

down_webapp: ## Pull Django image
	$(DOCKER_COMPOSE) -f $(compose) rm -s -f django flower celeryworker celerybeat

django_shell:  ## Open python terminal from django $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py shell

wagtail_sync: ## Wagtail sync Page fields (repeat every time you add a new language and to update the wagtailcore_page translations) $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py sync_page_translation_fields

wagtail_update_translation_field: ## Wagtail update translation fields, user this command first $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py update_translation_fields

django_createsuperuser: ## Create a super user from django $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py createsuperuser

django_bash: ## Open a bash terminar from django container using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django bash

django_test: ## Run tests from django container using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py test

django_fast: ## Run tests fast from django container using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py test --failfast

django_makemigrations: ## Run makemigrations from django container using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py makemigrations

django_migrate: ## Run migrate from django container using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py migrate

django_migrate_fresh_migrations: ## Run makemigrations and migrate from django container using $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django bash -c 'python manage.py makemigrations && python manage.py migrate'

django_makemessages: ## Run ./manage.py makemessages $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py makemessages --all

django_compilemessages: ## Run ./manage.py compilemessages $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py compilemessages 

django_dump_auth: ## Run manage.py dumpdata auth --indent=2 $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py dumpdata auth --indent=2  --output=fixtures/auth.json

django_load_auth: ## Run manage.py dumpdata auth --indent=2 $(compose)
	$(DOCKER_COMPOSE) -f $(compose) run --rm django python manage.py loaddata --database=default fixtures/auth.json

dump_data: BACKUP_FILE = dump_`date +%d-%m-%Y"_"%H_%M_%S`.sql
dump_data: ## Dump database into .sql $(compose)
	$(DOCKER_COMPOSE) -f $(compose) exec postgres bash -c 'pg_dumpall -c -U $$POSTGRES_USER -f /backups/"$(BACKUP_FILE)"'
	@echo "Database dump complete at $(BACKUP_FILE)"

restore_data: RESTORE_FILE = $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
restore_data: ## Restore database into from latest.sql file $(compose)
	@echo "Restoring Postgres data ..."
	@if [ -z "$(RESTORE_FILE)" ]; then \
		echo "File to restore not defined. Use: make restore_data compose=$(compose) <dump file name>.sql"; \
		exit 1; \
	fi; \
	echo "Restoring data from $(RESTORE_FILE) ..."; \
	$(DOCKER_COMPOSE) -f $(compose) exec postgres bash -c 'psql -U $$POSTGRES_USER -f /backups/"$(RESTORE_FILE)" $$POSTGRES_DB';
	@echo "Restore data from $(RESTORE_FILE) complete!"

############################################
## Atalhos Úteis                          ##
############################################

clean_container:  ## Remove all containers
	@docker rm $$(docker ps -a -q --no-trunc)

clean_project_containers:  ## Remove all containers
	@docker rm $$(docker ps -a --filter='name=upload_local*' -q --no-trunc)

clean_dangling_images:  ## Remove all dangling images
	@docker rmi -f $$(docker images --filter 'dangling=true' -q --no-trunc)

clean_dangling_volumes:  ## Remove all dangling volumes
	@docker volume rm $$(docker volume ls -f dangling=true -q)

clean_project_images:  ## Remove all images with "upload" on name
	@docker rmi -f $$(docker images --filter=reference='*upload*' -q)

volume_down:  ## Remove all volume
	$(DOCKER_COMPOSE) -f $(compose) down -v

clean_celery_logs:
	@sudo truncate -s 0 $$(docker inspect --format='{{.LogPath}}' $$($(DOCKER_COMPOSE) -f $(compose) ps -q celeryworker))

exclude_upload_production_django:  ## Exclude all productions containers
	@if [ -n "$$(docker images --format '{{.Repository}}:{{.Tag}}' | grep 'infrascielo/upload' | grep -v 'upload_production_postgres')" ]; then \
		docker rmi -f $$(docker images --format '{{.Repository}}:{{.Tag}}' | grep 'infrascielo/upload' | grep -v 'upload_production_postgres'); \
		echo "Excluded all upload production containers"; \
	else \
		echo "No images found for 'upload_production*'"; \
	fi

update: stop rm exclude_upload_production_django build up

update_webapp: pull_webapp down_webapp up
