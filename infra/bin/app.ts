import * as cdk from 'aws-cdk-lib';
import { RobotFleetStack } from '../lib/robot-fleet-stack';

const app = new cdk.App();
new RobotFleetStack(app, 'FleetDemoUsEast2', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || process.env.AWS_REGION || 'us-east-2'
  },
});
