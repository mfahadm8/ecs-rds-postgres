#!/usr/bin/env python3

import sys
from aws_cdk import App, Environment

from src.network_stack.network_stack import NetworkStack
from src.compute_stack.compute_stack import ComputeStack
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

app.synth()
