#!/usr/bin/env bash
# scripts/delete_deploy_user.sh
#
# Fully removes the probate-scraper-deploy IAM user:
# detaches all managed policies, deletes inline policies,
# deletes all access keys, then deletes the user.
#
# Usage:
#   ./scripts/delete_deploy_user.sh

set -euo pipefail

USERNAME="probate-scraper-deploy"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Deleting IAM user: $USERNAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if ! aws iam get-user --user-name "$USERNAME" &>/dev/null; then
  echo "  User '$USERNAME' does not exist — nothing to do."
  exit 0
fi

# Detach managed policies
ATTACHED=$(aws iam list-attached-user-policies --user-name "$USERNAME" \
  --query 'AttachedPolicies[*].PolicyArn' --output text)
for ARN in $ATTACHED; do
  aws iam detach-user-policy --user-name "$USERNAME" --policy-arn "$ARN"
  echo "  [ok]   Detached ${ARN##*/}"
done

# Delete inline policies
INLINE=$(aws iam list-user-policies --user-name "$USERNAME" \
  --query 'PolicyNames[*]' --output text)
for POLICY in $INLINE; do
  aws iam delete-user-policy --user-name "$USERNAME" --policy-name "$POLICY"
  echo "  [ok]   Deleted inline policy $POLICY"
done

# Delete access keys
KEYS=$(aws iam list-access-keys --user-name "$USERNAME" \
  --query 'AccessKeyMetadata[*].AccessKeyId' --output text)
for KEY_ID in $KEYS; do
  aws iam delete-access-key --user-name "$USERNAME" --access-key-id "$KEY_ID"
  echo "  [ok]   Deleted access key $KEY_ID"
done

# Delete user
aws iam delete-user --user-name "$USERNAME"
echo "  [ok]   Deleted user '$USERNAME'"
echo ""
