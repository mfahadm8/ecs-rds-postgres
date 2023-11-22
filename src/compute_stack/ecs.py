from typing import Dict

from aws_cdk import (
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecr as ecr,
    aws_ecs_patterns as ecs_patterns,
    aws_servicediscovery as servicediscovery,
    aws_ssm as ssm,
    aws_route53 as route53,
    aws_route53_targets as route53_targets,
    aws_logs,
    aws_cloudwatch as cloudwatch,
    Duration,
    aws_certificatemanager as cert,
    aws_elasticloadbalancingv2 as elbv2,
    aws_applicationautoscaling as autoscaling,
    aws_iam as iam,
    RemovalPolicy,
)
from constructs import Construct
from utils.ssm_util import SsmParameterFetcher


class Ecs(Construct):
    _config: Dict
    _cluster: ecs.ICluster
    _client_webapp_service: ecs.FargateService
    _backend_service: ecs.FargateService
    _vpc: ec2.Vpc

    def __init__(
        self,
        scope: Construct,
        id: str,
        config: Dict,
        vpc: ec2.Vpc,
    ) -> None:
        super().__init__(scope, id)
        self._config = config
        self._vpc = vpc
        # Create cluster control plane
        self.__create_ecs_cluster()
        # Create cluster worker nodes
        self.__create_client_ui_service()
        self.__create_backend_service()
        self.__create_redis_service()
        self.__setup_application_load_balancer()

    def __create_ecs_cluster(self):
        # Create ECS cluster
        self._cluster = ecs.Cluster(
            self,
            "thedb",
            cluster_name="thedb_cluster_" + self._config["stage"],
            vpc=self._vpc,
        )
        # Create private DNS namespace
        self.namespace = servicediscovery.PrivateDnsNamespace(
            self, "Namespace", name="ecs.local", vpc=self._vpc
        )

    def __create_client_ui_service(self):
        # Create Fargate task definition for ui
        react_app_api_key = SsmParameterFetcher(
            self,
            "SSMReactAppApiKey",
            region=self._config["aws_region"],
            parameter_name="/thedb/frontend/apikey",
        )
        # Import ECR repository for ui

        client_ui_repository = ecr.Repository.from_repository_arn(
            self,
            "ClientWebAppECRRepo",
            repository_arn=self._config["compute"]["ecs"]["client_webapp"]["repo_arn"],
        )

        # Create Fargate task definition for ui
        client_ui_taskdef = ecs.FargateTaskDefinition(
            self,
            "client-ui-taskdef",
            memory_limit_mib=self._config["compute"]["ecs"]["client_webapp"]["memory"],
            cpu=self._config["compute"]["ecs"]["client_webapp"]["cpu"],
        )

        client_ui_container = client_ui_taskdef.add_container(
            "ui-container",
            image=ecs.ContainerImage.from_ecr_repository(
                client_ui_repository,
                tag=self._config["compute"]["ecs"]["client_webapp"]["image_tag"],
            ),
            environment={
                "REACT_APP_BACKEND_URL": f"https://"
                + self._config["domain"]["backend_domain"],
                "REACT_APP_API_KEY": react_app_api_key.get_parameter(),
            },
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="clientwebapp",
                log_group=aws_logs.LogGroup(
                    self,
                    "ClientWebAppServerLogGroup",
                    log_group_name="/ecs/clientwebapp-server",
                    retention=aws_logs.RetentionDays.ONE_WEEK,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
            ),
        )

        client_ui_container.add_port_mappings(ecs.PortMapping(container_port=3000))

        capacity = [
            ecs.CapacityProviderStrategy(
                capacity_provider="FARGATE_SPOT",
                weight=self._config["compute"]["ecs"]["client_webapp"]["fargate_spot"][
                    "weight"
                ],
                base=self._config["compute"]["ecs"]["client_webapp"]["fargate_spot"][
                    "base"
                ],
            ),
            ecs.CapacityProviderStrategy(
                capacity_provider="FARGATE",
                weight=self._config["compute"]["ecs"]["client_webapp"]["fargate"][
                    "weight"
                ],
                base=self._config["compute"]["ecs"]["client_webapp"]["fargate"]["base"],
            ),
        ]

        client_webapp_security_group = ec2.SecurityGroup(
            self,
            "ClientWebAppSecurityGroup",
            vpc=self._vpc,
            allow_all_outbound=True,
        )
        client_webapp_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.all_traffic(),
        )

        # Create load-balanced Fargate service for ui
        self._client_webapp_service = ecs.FargateService(
            self,
            "clientwebapp-service",
            cluster=self._cluster,
            security_groups=[client_webapp_security_group],
            desired_count=self._config["compute"]["ecs"]["client_webapp"][
                "minimum_containers"
            ],
            service_name="clientwebapp-" + self._config["stage"],
            task_definition=client_ui_taskdef,
            assign_public_ip=True,
            capacity_provider_strategies=capacity,
            cloud_map_options={
                "name": "clientwebapp-" + self._config["stage"],
                "cloud_map_namespace": self.namespace,
            },
        )

        # Enable auto scaling for the frontend service
        scaling = autoscaling.ScalableTarget(
            self,
            "client-webapp-scaling",
            service_namespace=autoscaling.ServiceNamespace.ECS,
            resource_id=f"service/{self._cluster.cluster_name}/{self._client_webapp_service.service_name}",
            scalable_dimension="ecs:service:DesiredCount",
            min_capacity=self._config["compute"]["ecs"]["client_webapp"][
                "minimum_containers"
            ],
            max_capacity=self._config["compute"]["ecs"]["client_webapp"][
                "maximum_containers"
            ],
        )

        scaling.scale_on_metric(
            "ScaleToCPUWithMultipleDatapoints",
            metric=cloudwatch.Metric(
                namespace="AWS/ECS",
                metric_name="CPUUtilization",
            ),
            scaling_steps=[
                autoscaling.ScalingInterval(change=-1, lower=10),
                autoscaling.ScalingInterval(change=+1, lower=50),
                autoscaling.ScalingInterval(change=+3, lower=70),
            ],
            evaluation_periods=10,
            datapoints_to_alarm=6,
        )

    def __setup_application_load_balancer(self):
        # Create security group for the load balancer
        lb_security_group = ec2.SecurityGroup(
            self,
            "LoadBalancerSecurityGroup",
            vpc=self._cluster.vpc,
            allow_all_outbound=True,
        )
        lb_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(80),
        )
        lb_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
        )

        # Create load balancer
        self.lb = elbv2.ApplicationLoadBalancer(
            self,
            "LoadBalancer",
            vpc=self._cluster.vpc,
            internet_facing=True,
            security_group=lb_security_group,
        )

        # Create target group
        frontend_target_group = elbv2.ApplicationTargetGroup(
            self,
            "FrontendTargetGroup",
            vpc=self._cluster.vpc,
            port=3000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[self._client_webapp_service],
            health_check=elbv2.HealthCheck(
                path="/",
                protocol=elbv2.Protocol.HTTP,
                port="3000",
                interval=Duration.seconds(60),
                timeout=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=5,
            ),
        )

        backend_target_group = elbv2.ApplicationTargetGroup(
            self,
            "BackendTargetGroup",
            vpc=self._cluster.vpc,
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[self._backend_service],
            health_check=elbv2.HealthCheck(
                path="/vfx",
                protocol=elbv2.Protocol.HTTP,
                port="8000",
                healthy_http_codes="301",
                interval=Duration.seconds(60),
                timeout=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=5,
            ),
        )

        # Create HTTP listener for redirection
        http_listener = self.lb.add_listener(
            "HttpListener", port=80, protocol=elbv2.ApplicationProtocol.HTTP
        )

        http_listener.add_action(
            "HttpRedirect",
            action=elbv2.ListenerAction.redirect(
                port="443",
                protocol="HTTPS",
                permanent=True,
            ),
        )

        # Create HTTPS listener
        https_listener = self.lb.add_listener(
            "HttpsListener",
            port=443,
            protocol=elbv2.ApplicationProtocol.HTTPS,
            default_target_groups=[frontend_target_group],
        )

        # Add listener certificate (assuming you have a certificate in AWS Certificate Manager)
        https_listener.add_certificates(
            "ListenerCertificate",
            certificates=[
                elbv2.ListenerCertificate.from_arn(self._config["domain"]["cert_arn"])
            ],
        )

        # Create the listener rule
        rule = elbv2.CfnListenerRule(
            self,
            "ListenerRule",
            listener_arn=https_listener.listener_arn,
            priority=1,
            actions=[
                elbv2.CfnListenerRule.ActionProperty(
                    type="forward",
                    target_group_arn=backend_target_group.target_group_arn,
                )
            ],
            conditions=[
                elbv2.CfnListenerRule.RuleConditionProperty(
                    field="host-header",
                    values=[self._config["domain"]["backend_domain"]],
                )
            ],
        )

        rule.add_dependency(backend_target_group.node.default_child)

        hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "hostedZone",
            hosted_zone_id=self._config["domain"]["hostedzone_id"],
            zone_name=self._config["domain"]["hostedzone_name"],
        )

        route53.ARecord(
            self,
            "FrontendALBRecord",
            zone=hosted_zone,
            record_name=self._config["domain"]["frontend_domain"],
            target=route53.RecordTarget.from_alias(
                route53_targets.LoadBalancerTarget(self.lb)
            ),
        )

        route53.ARecord(
            self,
            "BackendALBRecord",
            zone=hosted_zone,
            record_name=self._config["domain"]["backend_domain"],
            target=route53.RecordTarget.from_alias(
                route53_targets.LoadBalancerTarget(self.lb)
            ),
        )

        ssm.StringParameter(
            self,
            "ServiceNameParameter",
            parameter_name="/thedb/infra/"
            + self._config["stage"]
            + "/ecs-loadbalancer-https-listener-arn",
            string_value=https_listener.listener_arn,
        )

    def __create_backend_service(self):
        db_name = SsmParameterFetcher(
            self,
            "SSMDefaultDB",
            region=self._config["aws_region"],
            parameter_name="/thedb/db/defaultdb",
        )
        db_host = SsmParameterFetcher(
            self,
            "SSMDbHost",
            region=self._config["aws_region"],
            parameter_name="/thedb/db/host",
        )
        db_port = SsmParameterFetcher(
            self,
            "SSMDbPort",
            region=self._config["aws_region"],
            parameter_name="/thedb/db/port",
        )
        db_user = SsmParameterFetcher(
            self,
            "SSMDbUser",
            region=self._config["aws_region"],
            parameter_name="/thedb/db/user",
        )
        db_password = SsmParameterFetcher(
            self,
            "SSMDbPassword",
            region=self._config["aws_region"],
            parameter_name="/thedb/db/password",
        )

        react_app_api_key = SsmParameterFetcher(
            self,
            "SSMReactAppApiKey2",
            region=self._config["aws_region"],
            parameter_name="/thedb/frontend/apikey",
        )

        backend_repository = ecr.Repository.from_repository_arn(
            self,
            "BackendECRRepo",
            repository_arn=self._config["compute"]["ecs"]["backend"]["repo_arn"],
        )
        # Create Fargate task definition for backendserver

        backendserver_taskdef = ecs.FargateTaskDefinition(
            self,
            "backend-taskdef",
            memory_limit_mib=self._config["compute"]["ecs"]["backend"]["memory"],
            cpu=self._config["compute"]["ecs"]["backend"]["cpu"],
        )

        backend_container = backendserver_taskdef.add_container(
            "backend-container",
            image=ecs.ContainerImage.from_ecr_repository(
                backend_repository,
                tag=self._config["compute"]["ecs"]["client_webapp"]["image_tag"],
            ),
            environment={
                "DB_HOST": db_host.get_parameter(),
                "DB_PORT": db_port.get_parameter(),
                "DB_NAME": db_name.get_parameter(),
                "DB_PASSWORD": db_password.get_parameter(),
                "DB_USER": db_user.get_parameter(),
                "API_KEY": react_app_api_key.get_parameter(),
            },
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="backend",
                log_group=aws_logs.LogGroup(
                    self,
                    "BackendServerLogGroup",
                    log_group_name="/ecs/backend-server",
                    retention=aws_logs.RetentionDays.ONE_WEEK,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
            ),
        )

        backend_container.add_port_mappings(ecs.PortMapping(container_port=8000))

        capacity = [
            ecs.CapacityProviderStrategy(
                capacity_provider="FARGATE_SPOT",
                weight=self._config["compute"]["ecs"]["backend"]["fargate_spot"][
                    "weight"
                ],
                base=self._config["compute"]["ecs"]["backend"]["fargate_spot"]["base"],
            ),
            ecs.CapacityProviderStrategy(
                capacity_provider="FARGATE",
                weight=self._config["compute"]["ecs"]["backend"]["fargate"]["weight"],
                base=self._config["compute"]["ecs"]["backend"]["fargate"]["base"],
            ),
        ]

        # Create standard Fargate service for backendserver
        self._backend_service = ecs.FargateService(
            self,
            "backend-service",
            cluster=self._cluster,
            desired_count=self._config["compute"]["ecs"]["backend"][
                "minimum_containers"
            ],
            service_name="backendserver-" + self._config["stage"],
            task_definition=backendserver_taskdef,
            assign_public_ip=True,
            vpc_subnets=ec2.SubnetSelection(
                availability_zones=[self._config["compute"]["ecs"]["db"]["az"]]
            ),
            capacity_provider_strategies=capacity,
            cloud_map_options={
                "name": "backendserver-" + self._config["stage"],
                "cloud_map_namespace": self.namespace,
            },
        )

        self._backend_service.connections.allow_from_any_ipv4(ec2.Port.tcp(8000))

        # Enable auto scaling for the backend service
        scaling = autoscaling.ScalableTarget(
            self,
            "backend-scaling",
            service_namespace=autoscaling.ServiceNamespace.ECS,
            resource_id=f"service/{self._cluster.cluster_name}/{self._backend_service.service_name}",
            scalable_dimension="ecs:service:DesiredCount",
            min_capacity=self._config["compute"]["ecs"]["backend"][
                "minimum_containers"
            ],
            max_capacity=self._config["compute"]["ecs"]["backend"][
                "maximum_containers"
            ],
        )

        scaling.scale_on_metric(
            "ScaleToCPUWithMultipleDatapoints",
            metric=cloudwatch.Metric(
                namespace="AWS/ECS",
                metric_name="CPUUtilization",
            ),
            scaling_steps=[
                autoscaling.ScalingInterval(change=-1, lower=10),
                autoscaling.ScalingInterval(change=+1, lower=50),
                autoscaling.ScalingInterval(change=+3, lower=70),
            ],
            evaluation_periods=10,
            datapoints_to_alarm=6,
        )

    def __create_redis_service(self):
        redis_taskdef = ecs.FargateTaskDefinition(
            self,
            "redis-taskdef",
            memory_limit_mib=self._config["compute"]["ecs"]["redis"]["memory"],
            cpu=self._config["compute"]["ecs"]["redis"]["cpu"],
        )

        redis_container = redis_taskdef.add_container(
            "redis-container",
            image=ecs.ContainerImage.from_registry(
                self._config["compute"]["ecs"]["redis"]["repo"]
                + ":"
                + self._config["compute"]["ecs"]["redis"]["image_tag"]
            ),
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="redis",
                log_group=aws_logs.LogGroup(
                    self,
                    "RedisServerLogGroup",
                    log_group_name="/ecs/redis-server",
                    retention=aws_logs.RetentionDays.ONE_WEEK,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
            ),
        )

        redis_container.add_port_mappings(ecs.PortMapping(container_port=6379))

        capacity = [
            ecs.CapacityProviderStrategy(
                capacity_provider="FARGATE_SPOT",
                weight=self._config["compute"]["ecs"]["redis"]["fargate_spot"][
                    "weight"
                ],
                base=self._config["compute"]["ecs"]["redis"]["fargate_spot"]["base"],
            ),
            ecs.CapacityProviderStrategy(
                capacity_provider="FARGATE",
                weight=self._config["compute"]["ecs"]["redis"]["fargate"]["weight"],
                base=self._config["compute"]["ecs"]["redis"]["fargate"]["base"],
            ),
        ]

        # Create standard Fargate service for redisserver
        self._redis_service = ecs.FargateService(
            self,
            "redis-service",
            cluster=self._cluster,
            desired_count=self._config["compute"]["ecs"]["redis"]["minimum_containers"],
            service_name="redisserver-" + self._config["stage"],
            task_definition=redis_taskdef,
            assign_public_ip=True,
            vpc_subnets=ec2.SubnetSelection(
                availability_zones=[self._config["compute"]["ecs"]["db"]["az"]]
            ),
            capacity_provider_strategies=capacity,
            cloud_map_options={
                "name": "redisserver-" + self._config["stage"],
                "cloud_map_namespace": self.namespace,
            },
        )

        self._redis_service.connections.allow_from_any_ipv4(ec2.Port.tcp(6379))

        # Enable auto scaling for the redis service
        scaling = autoscaling.ScalableTarget(
            self,
            "redis-scaling",
            service_namespace=autoscaling.ServiceNamespace.ECS,
            resource_id=f"service/{self._cluster.cluster_name}/{self._redis_service.service_name}",
            scalable_dimension="ecs:service:DesiredCount",
            min_capacity=self._config["compute"]["ecs"]["redis"]["minimum_containers"],
            max_capacity=self._config["compute"]["ecs"]["redis"]["maximum_containers"],
        )

        scaling.scale_on_metric(
            "ScaleToCPUWithMultipleDatapoints",
            metric=cloudwatch.Metric(
                namespace="AWS/ECS",
                metric_name="CPUUtilization",
            ),
            scaling_steps=[
                autoscaling.ScalingInterval(change=-1, lower=10),
                autoscaling.ScalingInterval(change=+1, lower=50),
                autoscaling.ScalingInterval(change=+3, lower=70),
            ],
            evaluation_periods=10,
            datapoints_to_alarm=6,
        )
