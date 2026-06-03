/**
 * Phase 2 sketch — EventBridge Scheduler → ECS RunTask for each job.
 *
 * Not deployed yet. Treat this as a wiring diagram.
 *
 * Three pieces:
 *   1. An IAM role for EventBridge Scheduler that can call ECS RunTask
 *      and pass the task role.
 *   2. One `CfnSchedule` per job, with a cron expression in MX timezone
 *      and a `Command` override that invokes the CLI from
 *      04-cli-entrypoint/__main__.py.
 *   3. No retry policy on the scheduler side — `claim_run` makes the
 *      job idempotent, so EventBridge's default at-least-once delivery
 *      is safe to fall back on if the RunTask call itself fails.
 */
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as scheduler from "aws-cdk-lib/aws-scheduler";
import { Construct } from "constructs";

interface ScheduledJob {
  name: string;
  cron: string;
  description: string;
}

interface Props {
  cluster: ecs.ICluster;
  taskDefinition: ecs.TaskDefinition;
  containerName: string;
  subnetSelection: ec2.SubnetSelection;
  securityGroup: ec2.ISecurityGroup;
}

const JOBS: ScheduledJob[] = [
  {
    name: "weekly_digest",
    cron: "cron(0 9 ? * MON *)",
    description: "Monday 09:00 MX — weekly forum digest.",
  },
  {
    name: "leaderboard_close",
    cron: "cron(0 18 ? * FRI *)",
    description: "Friday 18:00 MX — leaderboard close + awards.",
  },
  {
    name: "squad_health",
    cron: "cron(0 19 ? * SUN *)",
    description: "Sunday 19:00 MX — squad health DMs.",
  },
];

export class JobsStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: Props & cdk.StackProps) {
    super(scope, id, props);

    const role = new iam.Role(this, "SchedulerRole", {
      assumedBy: new iam.ServicePrincipal("scheduler.amazonaws.com"),
    });
    props.taskDefinition.taskRole?.grantPassRole(role);
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ecs:RunTask"],
        // Restrict to the specific task definition + cluster.
        resources: [props.taskDefinition.taskDefinitionArn],
        conditions: {
          ArnEquals: { "ecs:cluster": props.cluster.clusterArn },
        },
      }),
    );

    for (const job of JOBS) {
      new scheduler.CfnSchedule(this, `Schedule-${job.name}`, {
        description: job.description,
        scheduleExpression: job.cron,
        scheduleExpressionTimezone: "America/Mexico_City",
        flexibleTimeWindow: { mode: "OFF" },
        target: {
          arn: "arn:aws:scheduler:::aws-sdk:ecs:runTask",
          roleArn: role.roleArn,
          input: JSON.stringify({
            Cluster: props.cluster.clusterArn,
            TaskDefinition: props.taskDefinition.taskDefinitionArn,
            LaunchType: "FARGATE",
            NetworkConfiguration: {
              AwsvpcConfiguration: {
                Subnets: props.subnetSelection.subnets?.map((s) => s.subnetId),
                SecurityGroups: [props.securityGroup.securityGroupId],
                AssignPublicIp: "ENABLED",
              },
            },
            Overrides: {
              ContainerOverrides: [
                {
                  Name: props.containerName,
                  Command: ["python", "-m", "myapp.jobs", job.name],
                },
              ],
            },
          }),
          // No retry on the scheduler side — claim_run inside the job
          // makes a retry safe, and the ECS task's own logs are easier
          // to read than a chain of scheduler retries.
          retryPolicy: { maximumRetryAttempts: 0 },
        },
      });
    }
  }
}
