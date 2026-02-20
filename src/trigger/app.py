"""
Lambda handler for POST /real-estate/probate-leads/collin-tx/update

Starts an ECS Fargate task that runs the full Selenium scraper.
Returns 202 Accepted immediately — the scrape runs asynchronously.

Environment variables (injected by SAM/CloudFormation):
  ECS_CLUSTER_ARN       — ARN of the ECS cluster
  TASK_DEFINITION_ARN   — ARN of the scraper task definition
  TASK_SUBNETS          — comma-separated list of subnet IDs for awsvpc networking
  TASK_SECURITY_GROUP   — security group ID for the Fargate task
  TASK_EXECUTION_ROLE_ARN — ARN of the ECS task execution role (for iam:PassRole)
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

ecs = boto3.client("ecs")


def _response(status_code: int, body: dict, headers: dict = None) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            **(headers or {}),
        },
        "body": json.dumps(body),
    }


def handler(event, context):
    # Parse optional request body
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        body = {}

    scrape_run_id = body.get(
        "scrape_run_id",
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    )

    cluster_arn = os.environ["ECS_CLUSTER_ARN"]
    task_def_arn = os.environ["TASK_DEFINITION_ARN"]
    subnets = [s.strip() for s in os.environ["TASK_SUBNETS"].split(",")]
    security_group = os.environ["TASK_SECURITY_GROUP"]

    log.info("Starting ECS task — run_id=%s cluster=%s", scrape_run_id, cluster_arn)

    try:
        resp = ecs.run_task(
            cluster=cluster_arn,
            taskDefinition=task_def_arn,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnets,
                    "securityGroups": [security_group],
                    "assignPublicIp": "ENABLED",  # needed for internet access from public subnets
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": "scraper",
                        "environment": [
                            {"name": "SCRAPE_RUN_ID", "value": scrape_run_id},
                        ],
                    }
                ]
            },
        )
    except Exception as exc:
        log.exception("ecs.run_task failed: %s", exc)
        return _response(500, {"error": "Failed to start scrape task. Check CloudWatch logs."})

    failures = resp.get("failures", [])
    if failures:
        log.error("ECS run_task failures: %s", failures)
        return _response(500, {
            "error": "ECS task failed to start",
            "details": failures[0].get("reason", "unknown"),
        })

    task = resp["tasks"][0]
    task_arn = task["taskArn"]

    log.info("ECS task started — task_arn=%s", task_arn)

    return _response(202, {
        "status": "accepted",
        "task_arn": task_arn,
        "scrape_run_id": scrape_run_id,
        "message": (
            "Scrape job started. "
            "Monitor progress with: "
            f"aws logs tail /ecs/probate-scraper --follow"
        ),
    })
