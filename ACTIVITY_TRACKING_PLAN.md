# Activity Tracking Plan

## Overview
Comprehensive activity tracking system for user funnel journey including email sends, link clicks, and subscription actions.

## Database Schema

### Activities Table
- **Table Name**: `activities`
- **Primary Key**: `activity_id` (String)
- **GSI**: `user-activity-index` on `user_id` (Partition Key)

#### Fields:
```json
{
  "activity_id": "uuid",           // Primary key
  "user_id": "uuid",              // User who performed activity
  "activity_type": "string",       // Type of activity
  "timestamp": "ISO8601",         // When activity occurred
  "email_template": "string",      // Template used (for email_sent)
  "from_name": "string",          // From name used (for email_sent)
  "subject_line": "string",       // Subject line (for email_sent)
  "funnel_token": "string",       // Token for tracking
  "metadata": {                   // Additional context
    "to_email": "string",
    "price": 19,
    "lead_count": 10,
    "personalized": true,
    "user_agent": "string",
    "ip": "string"
  }
}
```

## Activity Types

### Email Activities
- `email_sent` - When funnel email is sent
- `magic_link_sent` - When login magic link is sent

### Link Click Activities  
- `subscribe_clicked` - When subscribe link in email is clicked
- `unsubscribe_clicked` - When unsubscribe link in email is clicked
- `link_clicked` - Generic link tracking

### Conversion Activities
- `signup_started` - When user starts signup process
- `signup_completed` - When user completes signup
- `payment_started` - When payment process starts
- `payment_completed` - When payment succeeds

## API Endpoints

### Admin Endpoints

#### POST /admin/activity/log
Log any activity manually (admin only)
```json
{
  "user_id": "uuid",
  "activity_type": "email_sent",
  "email_template": "prospect_email_v1.html",
  "from_name": "John Smith",
  "subject_line": "Your probate leads are ready",
  "funnel_token": "jwt.token.here",
  "metadata": {
    "to_email": "user@example.com",
    "price": 19,
    "lead_count": 10
  }
}
```

#### POST /admin/activity/query
Query activities for a user (admin only)
```json
{
  "user_id": "uuid",
  "limit": 50
}
```

### Public Endpoints

#### POST /activity/track
Track funnel link clicks (public, token-based)
```json
{
  "token": "funnel.jwt.token",
  "activity_type": "subscribe_clicked"
}
```

## Implementation Details

### Email Tracking
When `send_funnel_email()` is called:
1. Extract email details (template, from_name, subject)
2. Log `email_sent` activity with full context
3. Include funnel token for tracking

### Link Tracking
Email links include tracking:
- Subscribe: `https://app.com/signup?token={funnel_token}`
- Unsubscribe: `https://app.com/unsubscribe?token={funnel_token}`

Frontend calls `/activity/track` when:
- User clicks subscribe link
- User clicks unsubscribe link
- User starts signup process
- User completes signup

### Automatic Activity Logging

#### Funnel Email Send
```python
log_activity(
    user_id=user["user_id"],
    activity_type="email_sent",
    email_template="prospect_email_v1.html",
    from_name=from_name,
    subject_line=subject,
    funnel_token=token,
    metadata={
        "to_email": email_address,
        "price": price,
        "lead_count": len(leads),
        "personalized": bool(first_name),
    }
)
```

#### Magic Link Send
```python
log_activity(
    user_id=user["user_id"],
    activity_type="magic_link_sent",
    metadata={
        "to_email": email,
    }
)
```

## Frontend Integration

### Email Links
```html
<!-- Subscribe Link -->
<a href="https://app.com/signup?token={funnel_token}" 
   onclick="trackActivity('subscribe_clicked', '{funnel_token}')">
  Subscribe Now
</a>

<!-- Unsubscribe Link -->
<a href="https://app.com/unsubscribe?token={funnel_token}"
   onclick="trackActivity('unsubscribe_clicked', '{funnel_token}')">
  Unsubscribe
</a>
```

### JavaScript Tracking
```javascript
async function trackActivity(activityType, token) {
  try {
    await fetch('/real-estate/probate-leads/activity/track', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: token,
        activity_type: activityType
      })
    });
  } catch (error) {
    console.error('Activity tracking failed:', error);
  }
}

// Track signup completion
trackActivity('signup_completed', funnelToken);
```

## Analytics & Reporting

### User Journey Tracking
Query activities to reconstruct user journey:
```sql
-- Get user's complete funnel journey
SELECT * FROM activities 
WHERE user_id = 'user-uuid' 
ORDER BY timestamp DESC;
```

### Conversion Metrics
Track conversion rates:
- Email sent → Subscribe clicked
- Subscribe clicked → Signup completed  
- Signup completed → Payment completed

### A/B Testing
Compare performance of:
- Different email templates
- Different subject lines
- Different from names

## Security Considerations

### Token Validation
- Funnel tokens expire after 30 days
- Activities require valid token
- Rate limiting on tracking endpoint

### Privacy
- IP addresses stored for security analysis
- User agents for technical debugging
- No PII in activity metadata beyond email

## Deployment Requirements

### Environment Variables
```
ACTIVITIES_TABLE_NAME=activities
USER_ACTIVITY_GSI=user-activity-index
```

### DynamoDB Setup
```bash
# Create activities table
aws dynamodb create-table \
  --table-name activities \
  --attribute-definitions \
    AttributeName=activity_id,AttributeType=S \
    AttributeName=user_id,AttributeType=S \
  --key-schema \
    AttributeName=activity_id,KeyType=HASH \
  --global-secondary-indexes \
    IndexName=user-activity-index,KeySchema=[{AttributeName=user_id,KeyType=HASH}],Projection={ProjectionType=ALL} \
  --billing-mode PAY_PER_REQUEST
```

## Testing Strategy

### Unit Tests
- Activity model serialization
- API endpoint validation
- Token verification

### Integration Tests  
- Email send tracking
- Link click tracking
- Admin query endpoints

### End-to-End Tests
- Complete user journey tracking
- Conversion funnel accuracy
- Performance under load

## Benefits

1. **Complete Visibility**: Track every step of user journey
2. **Conversion Optimization**: Identify drop-off points
3. **A/B Testing**: Compare email performance
4. **Security**: Track suspicious activity patterns
5. **Compliance**: Audit trail for user actions
6. **Analytics**: Data-driven decision making

## Future Enhancements

1. **Real-time Dashboard**: Live activity monitoring
2. **Automated Workflows**: Trigger actions based on activities
3. **Advanced Analytics**: Machine learning for predictions
4. **Multi-channel Tracking**: SMS, push notifications
5. **Privacy Controls**: User activity deletion options
