from typing import Dict

from aws_cdk import (
    aws_ec2 as ec2,
    Stack
)
from utils.stack_util import add_tags_to_stack
from .ecs import Ecs
from utils.ssm_util import SsmParameterFetcher
from constructs import Construct
class ComputeStack(Stack):

    def __init__(self, scope:Construct, id: str,
                 config: Dict,
                 vpc:ec2.IVpc,
                 ** kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Apply common tags to stack resources.
        add_tags_to_stack(self, config)
        # create the ecs cluster
        self._ecs=Ecs(self, 'Ecs', config, vpc)
