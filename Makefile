LOCAL_VENV_NAME=.venv
PYTHON=python3
STACK?=NetworkStack

STAGE?= dev
ifeq ($(STAGE), prod)
	REGION=eu-west-2
else
	REGION=eu-west-2
endif

.PHONY: all test lint synth diff deploy

local-venv:
	$(PYTHON) -m venv .venv

install-dependencies:
	pip install -r requirements.txt

lint:
	flake8 $(shell git ls-files '*.py')

test:
	pytest

synth:
	@cdk synth -c stage=$(STAGE) --output=cdk.out/$(STAGE) $(STACK)-$(STAGE)

deploy:
	@cdk deploy --app=cdk.out/$(STAGE) $(STACK)-$(STAGE)

diff:
	@cdk diff -c stage=$(STAGE) $(STACK)-$(STAGE)

destroy:
	@cdk destroy -c stage=$(STAGE) $(STACK)-$(STAGE)

bootstrapp-cdk-toolkit:
	@cdk bootstrap aws://354789122408/$(REGION) -c stage=$(STAGE)