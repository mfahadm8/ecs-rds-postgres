from typing import Dict

from aws_cdk import aws_ec2 as ec2, aws_ssm as ssm, Stack

from utils.stack_util import add_tags_to_stack
from .vpc import Vpc
from constructs import Construct


class NetworkStack(Stack):
    _vpc: ec2.IVpc
    config: Dict

    def __init__(self, scope: Construct, id: str, config: Dict, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)
        self.config = config
        # Apply common tags to stack resources.
        add_tags_to_stack(self, config)

        vpcConstruct = Vpc(self, "Vpc", config)
        self._vpc = vpcConstruct.vpc
        self.__push_vpc_id_cidr()
        self.__push_subnets_route_tables_ids()

    def __push_vpc_id_cidr(self):
        vpc_id = self._vpc.vpc_id
        vpc_cidr_block = self._vpc.vpc_cidr_block

        ssm.StringParameter(
            scope=self,
            id="vpcId",
            tier=ssm.ParameterTier.STANDARD,
            string_value=vpc_id,
            parameter_name=self.config["ssm_infra"] + "vpc",
        )

        ssm.StringParameter(
            scope=self,
            id="vpcCidr",
            tier=ssm.ParameterTier.STANDARD,
            string_value=vpc_cidr_block,
            parameter_name=self.config["ssm_infra"] + "vpcCidrBlock",
        )

    def __push_subnets_route_tables_ids(self):
        if self.config["network"]["vpc"]["create_natgateway"] == 1:
            private_subnets = self._vpc.select_subnets(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ).subnets

            for index, subnet in enumerate(private_subnets):
                ssm.StringParameter(
                    scope=self,
                    id=f"privateSubnet{index+1}",
                    tier=ssm.ParameterTier.STANDARD,
                    string_value=subnet.subnet_id,
                    parameter_name=self.config["ssm_infra"] + f"privateSubnet{index+1}",
                )

                ssm.StringParameter(
                    scope=self,
                    id=f"privateRouteTable{index+1}",
                    tier=ssm.ParameterTier.STANDARD,
                    string_value=subnet.route_table.route_table_id,
                    parameter_name=self.config["ssm_infra"]
                    + f"privateRouteTable{index+1}",
                )

                ssm.StringParameter(
                    scope=self,
                    id=f"privateSubnetAz{index+1}",
                    tier=ssm.ParameterTier.STANDARD,
                    string_value=subnet.availability_zone,
                    parameter_name=self.config["ssm_infra"]
                    + f"privateSubnetAz{index+1}",
                )

        public_subnets = self._vpc.select_subnets(
            subnet_type=ec2.SubnetType.PUBLIC
        ).subnets

        for index, subnet in enumerate(public_subnets):
            ssm.StringParameter(
                scope=self,
                id=f"publicSubnet{index+1}",
                tier=ssm.ParameterTier.STANDARD,
                string_value=subnet.subnet_id,
                parameter_name=self.config["ssm_infra"] + f"publicSubnet{index+1}",
            )

            ssm.StringParameter(
                scope=self,
                id=f"publicRouteTable{index+1}",
                tier=ssm.ParameterTier.STANDARD,
                string_value=subnet.route_table.route_table_id,
                parameter_name=self.config["ssm_infra"] + f"publicRouteTable{index+1}",
            )

            ssm.StringParameter(
                scope=self,
                id=f"publicSubnetAz{index+1}",
                tier=ssm.ParameterTier.STANDARD,
                string_value=subnet.availability_zone,
                parameter_name=self.config["ssm_infra"] + f"publicSubnetAz{index+1}",
            )
