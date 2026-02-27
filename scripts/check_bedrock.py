#!/usr/bin/env python3
"""
Verify that the configured Bedrock model is accessible in this account/region.

Run this before deploying ParseDocumentFunction to confirm that the model
can be invoked.  Exits 0 on success, 1 on any failure.

Usage:
    pipenv run python scripts/check_bedrock.py

    # Override model or region:
    BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0 \\
    AWS_DEFAULT_REGION=us-east-1 \\
    pipenv run python scripts/check_bedrock.py

Environment variables:
    BEDROCK_MODEL_ID   Model to test (default: anthropic.claude-3-haiku-20240307-v1:0)
    AWS_DEFAULT_REGION AWS region    (default: us-east-1)
"""

import os
import sys

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-haiku-20240307-v1:0",
)
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
RESET  = "\033[0m"


def main() -> int:
    print(f"\n{'='*70}")
    print(f"  Bedrock access check")
    print(f"  Model:  {MODEL_ID}")
    print(f"  Region: {REGION}")
    print(f"{'='*70}\n")

    try:
        client = boto3.client("bedrock-runtime", region_name=REGION)
        response = client.converse(
            modelId=MODEL_ID,
            messages=[{
                "role":    "user",
                "content": [{"text": "Reply with the single word: ok"}],
            }],
            inferenceConfig={"maxTokens": 10, "temperature": 0},
        )
        reply = response["output"]["message"]["content"][0]["text"].strip()
        print(f"  {GREEN}✓{RESET}  Model responded: {reply!r}")
        print(f"\n  {GREEN}PASSED{RESET} — Bedrock access confirmed, safe to deploy.\n")
        return 0

    except NoCredentialsError:
        print(f"  {RED}✗{RESET}  No AWS credentials found.\n")
        print("  Configure credentials via ~/.aws/credentials, AWS_PROFILE,")
        print("  or AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY env vars.\n")
        return 1

    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        msg  = exc.response["Error"]["Message"]
        print(f"  {RED}✗{RESET}  {code}: {msg}\n")

        if "use case details" in msg.lower():
            print(f"  {YELLOW}ACTION REQUIRED{RESET}: Submit Anthropic use case details.\n")
            print("  AWS requires a one-time use case form for Anthropic models.")
            print("  Steps:")
            print(f"    1. Open the Bedrock model catalog:")
            print(f"       https://{REGION}.console.aws.amazon.com/bedrock/home?region={REGION}#/model-catalog")
            print(f"    2. Search for 'Claude 3 Haiku'")
            print(f"    3. Click the model → complete the use case details form")
            print(f"    4. Wait for approval (usually instant) then re-run: make check-bedrock\n")

        elif code == "AccessDeniedException":
            print(f"  {YELLOW}Fix{RESET}: IAM role/user is missing bedrock:InvokeModel permission.")
            print(f"  Add this to the relevant IAM policy:")
            print(f'    {{"Effect": "Allow", "Action": "bedrock:InvokeModel", "Resource": "*"}}\n')

        elif code == "ValidationException" and "on-demand throughput" in msg.lower():
            print(f"  {YELLOW}Fix{RESET}: This model requires a cross-region inference profile (us.* prefix).")
            print(f"  Claude 3 Haiku supports on-demand; if you see this the model ID is wrong.")
            print(f"  Expected: anthropic.claude-3-haiku-20240307-v1:0\n")

        elif code in ("ResourceNotFoundException", "ValidationException"):
            print(f"  {YELLOW}Fix{RESET}: Model '{MODEL_ID}' not found in {REGION}.")
            print(f"  Check that the model ID is correct and available in this region.\n")

        print(f"  {RED}FAILED{RESET}\n")
        return 1

    except Exception as exc:  # noqa: BLE001
        print(f"  {RED}✗{RESET}  Unexpected error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
