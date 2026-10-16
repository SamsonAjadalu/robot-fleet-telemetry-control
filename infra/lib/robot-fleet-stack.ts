import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as patterns from 'aws-cdk-lib/aws-ecs-patterns';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as elasticache from 'aws-cdk-lib/aws-elasticache';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';

export class RobotFleetStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    cdk.Tags.of(this).add('Project', 'Robot Fleet Telemetry & Control');

    const runService = String(this.node.tryGetContext('runService')) === 'true';
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 }
      ],
    });
    const cluster = new ecs.Cluster(this, 'Cluster', {
      vpc, clusterName: 'fleet-demo'
    });
    const repository = new ecr.Repository(this, 'BackendRepository', {
      repositoryName: 'fleet-demo-backend',
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    const database = new rds.DatabaseInstance(this, 'Database', {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_15
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
      databaseName: 'robot_fleet',
      credentials: rds.Credentials.fromGeneratedSecret('robot_admin'),
      allocatedStorage: 20,
      multiAz: false,
      deletionProtection: false,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      publiclyAccessible: false,
    });

    const redisSecurityGroup = new ec2.SecurityGroup(this, 'RedisSecurityGroup', { vpc });
    const redisSubnetGroup = new elasticache.CfnSubnetGroup(this, 'RedisSubnetGroup', {
      description: 'Robot Fleet Redis private subnets',
      subnetIds: vpc.privateSubnets.map(subnet => subnet.subnetId),
    });
    const redis = new elasticache.CfnCacheCluster(this, 'Redis', {
      engine: 'redis',
      engineVersion: '7.1',
      cacheNodeType: 'cache.t4g.micro',
      numCacheNodes: 1,
      cacheSubnetGroupName: redisSubnetGroup.ref,
      vpcSecurityGroupIds: [redisSecurityGroup.securityGroupId],
    });

    const logGroup = new logs.LogGroup(this, 'ApiLogs', {
      logGroupName: '/fleet-demo/api',
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    const api = new patterns.ApplicationLoadBalancedFargateService(this, 'Api', {
      cluster,
      serviceName: 'fleet-demo-api',
      publicLoadBalancer: true,
      desiredCount: 2,
      cpu: 512,
      memoryLimitMiB: 1024,
      taskSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      taskImageOptions: {
        image: ecs.ContainerImage.fromEcrRepository(repository, 'latest'),
        containerPort: 8000,
        environment: {
          DB_HOST: database.dbInstanceEndpointAddress,
          DB_PORT: '5432',
          DB_NAME: 'robot_fleet',
          DB_USER: 'robot_admin',
          REDIS_URL: `redis://${redis.attrRedisEndpointAddress}:6379/0`,
          REDIS_REQUIRED: 'true',
          REDIS_CHANNEL: 'robot-fleet:websocket',
          CORS_ALLOW_ORIGINS: '',
        },
        secrets: {
          DB_PASSWORD: ecs.Secret.fromSecretsManager(database.secret!, 'password'),
        },
        logDriver: ecs.LogDrivers.awsLogs({ logGroup, streamPrefix: 'api' }),
      },
    });
    // The first deployment publishes infrastructure before the ECR image exists.
    if (!runService) {
      (api.service.node.defaultChild as ecs.CfnService).desiredCount = 0;
    }
    api.targetGroup.configureHealthCheck({ path: '/ready', healthyHttpCodes: '200' });
    api.service.connections.allowTo(database, ec2.Port.tcp(5432));
    api.service.connections.allowTo(redisSecurityGroup, ec2.Port.tcp(6379));

    const frontendBucket = new s3.Bucket(this, 'FrontendBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      autoDeleteObjects: false,
    });

    const apiOrigin = new origins.HttpOrigin(api.loadBalancer.loadBalancerDnsName, {
      protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
    });
    const apiBehavior: cloudfront.BehaviorOptions = {
      origin: apiOrigin,
      viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
      cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
      originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
    };
    const spaRewrite = new cloudfront.Function(this, 'SpaRewrite', {
      code: cloudfront.FunctionCode.fromInline(`
function handler(event) {
  var request = event.request;
  var path = request.uri;
  if (path === '/' || (path.indexOf('.') === -1 && path.indexOf('/maps/') !== 0)) {
    request.uri = '/index.html';
  }
  return request;
}`),
    });
    const distribution = new cloudfront.Distribution(this, 'FrontendDistribution', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(frontendBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        functionAssociations: [{
          function: spaRewrite,
          eventType: cloudfront.FunctionEventType.VIEWER_REQUEST,
        }],
      },
      additionalBehaviors: Object.fromEntries(
        ['/api/*', '/ws/*', '/health', '/ready', '/status', '/telemetry/*', '/docs', '/openapi.json']
          .map(pattern => [pattern, apiBehavior])
      ),
      defaultRootObject: 'index.html',
    });

    new cdk.CfnOutput(this, 'EcrRepositoryUri', { value: repository.repositoryUri });
    new cdk.CfnOutput(this, 'FrontendBucketName', { value: frontendBucket.bucketName });
    new cdk.CfnOutput(this, 'CloudFrontDomainName', { value: distribution.distributionDomainName });
    new cdk.CfnOutput(this, 'CloudFrontDistributionId', { value: distribution.distributionId });
  }
}
