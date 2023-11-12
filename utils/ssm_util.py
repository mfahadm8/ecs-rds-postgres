from aws_cdk.custom_resources import AwsCustomResource,AwsSdkCall,AwsCustomResourcePolicy,PhysicalResourceId
from aws_cdk import aws_iam
from constructs import Construct 
import datetime 

class SsmParameterFetcher(AwsCustomResource):
    def __init__(self, scope: Construct, id: str, region: str, parameter_name: str, *args, **kwargs):
        ssmAwsCall=AwsSdkCall(
            service='SSM',
            action= 'getParameter',
            parameters= {
                "Name": parameter_name,
                "WithDecryption": True
            },
            region=region,
            physical_resource_id=PhysicalResourceId.of( str(datetime.datetime.now())) # Update physical id to always fetch the latest version}
        )

        super().__init__(
            scope, 
            id,
            on_update=ssmAwsCall,
            policy=AwsCustomResourcePolicy.from_statements([
                aws_iam.PolicyStatement(
                    resources= ['*'],
                    actions= ['ssm:GetParameter'],
                    effect= aws_iam.Effect.ALLOW
                    )
                ]),
            *args,
            **kwargs)

    
    def get_parameter(self):
        return self.get_response_field('Parameter.Value')