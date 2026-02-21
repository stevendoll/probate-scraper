#!/usr/bin/env bash
# scripts/create_deploy_user.sh
#
# Creates an IAM user for GitHub Actions CI/CD with the minimum permissions
# needed to deploy the probate-scraper stack, then prints the access key so
# you can add it to GitHub Secrets.
#
# Usage:
#   ./scripts/create_deploy_user.sh
#
# Prerequisites:
#   - AWS CLI configured with credentials that have IAM admin access
#   - Run once; re-running is safe (skips already-created resources)
#
# After running, add these to GitHub → Settings → Secrets and variables → Actions:
#   AWS_ACCESS_KEY_ID     (printed at the end)
#   AWS_SECRET_ACCESS_KEY (printed at the end)

set -euo pipefail

USERNAME="probate-scraper-deploy"
REGION="us-east-1"

# ── Managed policies ────────────────────────────────────────────────────────
MANAGED_POLICIES=(
  "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess"
  "arn:aws:iam::aws:policy/AWSCloudFormationFullAccess"
  "arn:aws:iam::aws:policy/AmazonS3FullAccess"
  "arn:aws:iam::aws:policy/AWSLambda_FullAccess"
  "arn:aws:iam::aws:policy/AmazonAPIGatewayAdministrator"
  "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
  "arn:aws:iam::aws:policy/AmazonECS_FullAccess"
  "arn:aws:iam::aws:policy/AmazonEventBridgeFullAccess"
  "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
  "arn:aws:iam::aws:policy/IAMFullAccess"
)

# ── Inline policy: EC2 (VPC/subnet discovery + security group management) ──
EC2_POLICY=$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DescribeNetwork",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeAvailabilityZones"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ManageScraperSecurityGroup",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateSecurityGroup",
        "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupEgress",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupEgress",
        "ec2:RevokeSecurityGroupIngress",
        "ec2:CreateTags"
      ],
      "Resource": "*"
    }
  ]
}
EOF
)

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Creating IAM deploy user: $USERNAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. Create user (idempotent) ─────────────────────────────────────────────
if aws iam get-user --user-name "$USERNAME" &>/dev/null; then
  echo "  [skip] User '$USERNAME' already exists"
else
  aws iam create-user --user-name "$USERNAME" \
    --tags Key=Project,Value=probate-scraper Key=ManagedBy,Value=create_deploy_user.sh
  echo "  [ok]   Created user '$USERNAME'"
fi

# ── 2. Attach managed policies ──────────────────────────────────────────────
echo ""
echo "  Attaching managed policies..."
for ARN in "${MANAGED_POLICIES[@]}"; do
  POLICY_NAME="${ARN##*/}"
  aws iam attach-user-policy --user-name "$USERNAME" --policy-arn "$ARN"
  echo "    ✓  $POLICY_NAME"
done

# ── 3. Inline EC2 policy ────────────────────────────────────────────────────
echo ""
aws iam put-user-policy \
  --user-name "$USERNAME" \
  --policy-name "EC2NetworkAndSecurityGroups" \
  --policy-document "$EC2_POLICY"
echo "  [ok]   Attached inline EC2 policy"

# ── 4. Create access key ────────────────────────────────────────────────────
echo ""
echo "  Creating access key..."
KEY_JSON=$(aws iam create-access-key --user-name "$USERNAME")
ACCESS_KEY_ID=$(echo "$KEY_JSON" | python3 -c "import sys,json; k=json.load(sys.stdin)['AccessKey']; print(k['AccessKeyId'])")
SECRET_ACCESS_KEY=$(echo "$KEY_JSON" | python3 -c "import sys,json; k=json.load(sys.stdin)['AccessKey']; print(k['SecretAccessKey'])")

# ── 5. Print results ────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Done! Add these to GitHub → Settings → Secrets and variables → Actions"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  AWS_ACCESS_KEY_ID     = $ACCESS_KEY_ID"
echo "  AWS_SECRET_ACCESS_KEY = $SECRET_ACCESS_KEY"
echo ""
echo "  ⚠️  This is the only time the secret key is shown. Save it now."
echo ""
echo "  To verify the user:"
echo "    aws iam list-attached-user-policies --user-name $USERNAME"
echo ""
echo "  To delete the user and all its keys/policies later:"
echo "    ./scripts/delete_deploy_user.sh"
echo ""
