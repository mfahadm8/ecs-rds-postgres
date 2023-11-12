#!/usr/bin/env python3

import sys
from aws_cdk import App, Environment

from src.network_stack.network_stack import NetworkStack
from src.compute_stack.compute_stack import ComputeStack
from src.deploy_stack.deploy_stack import DeployStack
from src.maintainance_stack.maintainance_stack import MaintainanceStack
from utils import config_util

app = App()

# Get target stage from cdk context
stage = app.node.try_get_context("stage")
if stage is None or stage == "unknown":
    sys.exit(
        "You need to set the target stage." " USAGE: cdk <command> -c stage=dev <stack>"
    )

# Load stage config and set cdk environment
config = config_util.load_config(stage)
env = Environment(
    account=config["aws_account"],
    region=config["aws_region"],
)

network_stack = NetworkStack(
    app, "NetworkStack-" + config["stage"], config=config, env=env
)

compute_stack = ComputeStack(
    app,
    "ComputeStack-" + config["stage"],
    vpc=network_stack._vpc,
    config=config,
    env=env,
)

cicd_stack = DeployStack(
    app,
    "DeployStack-" + config["stage"],
    config=config,
    ecs_cluster=compute_stack._ecs._cluster,
    client_webapp_service=compute_stack._ecs._client_webapp_service,
    backend_service=compute_stack._ecs._backend_service,
    env=env,
)


cicd_stack = MaintainanceStack(
    app,
    "MaintainanceStack-" + config["stage"],
    config=config,
    env=env,
)
app.synth()
