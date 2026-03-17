# Customer Journeys - User Flows & UI Components

Comprehensive overview of all customer journey user flows and UI components implemented in the probate leads system.

## 🎯 Overview

The system now supports **3 distinct customer journeys** with specialized email templates, UI components, and API endpoints:

1. **Coming Soon Journey** - Build anticipation before product launch
2. **Prospect Journey** - Enhanced version of existing lead generation
3. **Free Trial Journey** - Risk-free 14-day product trial

---

## 🛤️ User Flows

### 1. Coming Soon Journey

**Goal**: Build waitlist of interested users before product launch

```
Admin sends waitlist invitation
        ↓
User receives "invited_to_waitlist" email
        ↓
User clicks CTA → /waitlist/signup
        ↓
User enters email → POST /journeys/accept-waitlist
        ↓
User sees confirmation → /waitlist/success
        ↓
Status: invited_to_waitlist → accepted_waitlist
        ↓
[Later] Admin sends launch invitations
        ↓
User receives "invited_to_join" email with subscribe link
        ↓
User clicks → /signup?token=xxx → Stripe checkout
        ↓
Status: accepted_waitlist → invited_to_join → subscribed
```

**Email Templates**:
- `invited_to_waitlist_default.html` - Waitlist invitation with CTA
- `accepted_waitlist_default.html` - Confirmation with countdown timer
- `invited_to_join_default.html` - Launch notification with pricing

**UI Components**:
- `WaitlistForm` - Email capture with success states
- `WaitlistSignup` page - Full waitlist signup experience
- `WaitlistSuccess` page - Confirmation with next steps

**API Endpoints**:
- `POST /journeys/invite-to-waitlist` (admin)
- `POST /journeys/accept-waitlist` (public)
- `POST /journeys/invite-to-join-from-waitlist` (admin)

---

### 2. Prospect Journey (Enhanced)

**Goal**: Convert prospects with sample leads and professional presentation

```
User requests magic link OR admin sends prospect email
        ↓
New users: receives "prospect" email with sample leads
        ↓
User clicks subscribe CTA → /signup?token=xxx
        ↓
Stripe checkout → subscription activated
        ↓
Status: inbound → prospect → active
```

**Email Templates**:
- `prospect_default.html` - Professional email with lead tables
- `prospect_default.txt` - Text fallback version

**UI Components**:
- Enhanced `Signup` page (existing, improved styling)
- Professional email design with lead data tables

**API Endpoints**:
- Existing prospect system enhanced with new templates

---

### 3. Free Trial Journey

**Goal**: Let users try the product risk-free before subscribing

```
Admin sends trial invitation
        ↓
User receives "invited_to_trial" email
        ↓
User clicks CTA → /trial/signup?token=xxx
        ↓
User clicks "Start Trial" → POST /journeys/start-trial
        ↓
Status: invited_to_trial → trialing
        ↓
User logs in → sees trial banner on dashboard
        ↓
[During trial] User sees countdown + subscribe prompts
        ↓
User subscribes OR trial expires after 14 days
        ↓
Status: trialing → active | trial_expired
```

**Email Templates**:
- `invited_to_trial_default.html` - Professional trial invitation
- `trialing_default.html` - Trial reminder (future)
- `trial_expired_default.html` - Convert after expiry (future)

**UI Components**:
- `TrialSignup` page - Full trial invitation experience
- `TrialBanner` - Countdown banner with subscribe CTA
- Enhanced `Dashboard` - Shows trial status

**API Endpoints**:
- `POST /journeys/invite-to-trial` (admin)
- `POST /journeys/start-trial` (public)
- `GET /journeys/trial-status/{user_id}` (auth)

---

## 🎨 UI Components Inventory

### Core Journey Components

| Component | Location | Purpose | Props |
|-----------|----------|---------|--------|
| `TrialBanner` | `/components/trial-banner.tsx` | Shows trial countdown on dashboard | `onSubscribe?: () => void` |
| `WaitlistForm` | `/components/waitlist-form.tsx` | Email capture for waitlist | `onSuccess?, className?, variant?` |

### Page Components

| Page | Route | Purpose | Journey |
|------|-------|---------|---------|
| `WaitlistSignup` | `/waitlist/signup` | Waitlist email capture | Coming Soon |
| `WaitlistSuccess` | `/waitlist/success` | Confirmation after joining waitlist | Coming Soon |
| `TrialSignup` | `/trial/signup` | Free trial invitation acceptance | Free Trial |
| `Signup` | `/signup` | Prospect subscription signup | Prospect |
| `Dashboard` | `/dashboard` | Enhanced with trial banner | All |

### Enhanced Existing Components

| Component | Enhancement | Journey Support |
|-----------|-------------|----------------|
| `Dashboard` | Added `TrialBanner` integration | Free Trial |
| `Signup` | Improved styling, existing functionality | Prospect |

---

## 📧 Email Template System

### Template Structure

```
src/api/templates/journeys/
├── coming_soon/
│   ├── invited_to_waitlist_default.html
│   ├── accepted_waitlist_default.html
│   └── invited_to_join_default.html
├── free_trial/
│   ├── invited_to_trial_default.html
│   ├── trialing_default.html (future)
│   └── trial_expired_default.html (future)
├── prospect/
│   ├── prospect_default.html
│   └── prospect_default.txt
└── subjects/
    ├── coming_soon_invite.txt
    ├── coming_soon_accepted.txt
    ├── coming_soon_launch.txt
    ├── free_trial_invite.txt
    ├── free_trial_reminder.txt
    ├── free_trial_expired.txt
    └── prospect.txt
```

### Template Features

- **Jinja2-powered** with dynamic context
- **Template variants** support (`default`, `a`, `b` for A/B testing)
- **Mobile-responsive** HTML with text fallbacks
- **Professional styling** with Tailwind-inspired CSS
- **Dynamic content** (user names, lead data, pricing, countdowns)
- **Fallback system** for missing templates

---

## 🔧 API Integration

### Database Schema Changes

**User Model Enhancements**:
```typescript
interface User {
  // Existing fields...
  trial_expires_on: string      // ISO timestamp for trial expiration
  journey_type: string          // "coming_soon" | "prospect" | "free_trial"
  journey_step: string          // Current step in journey
}
```

**Valid Status Values**:
```
// Existing
"active", "inactive", "canceled", "past_due", "trialing", "free_trial", "unsubscribed"

// New Journey Statuses
"inbound", "prospect", "invited_to_waitlist", "accepted_waitlist",
"invited_to_join", "invited_to_trial", "trial_expired"
```

### Customer Journey API Endpoints

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `POST` | `/journeys/invite-to-waitlist` | Admin | Send waitlist invitations to email list |
| `POST` | `/journeys/accept-waitlist` | Public | User accepts waitlist invitation |
| `POST` | `/journeys/invite-to-join-from-waitlist` | Admin | Send launch invitations to waitlist users |
| `POST` | `/journeys/invite-to-trial` | Admin | Send trial invitations to email list |
| `POST` | `/journeys/start-trial` | Public | User starts free trial with JWT token |
| `GET` | `/journeys/trial-status/{user_id}` | Auth | Get trial status for UI components |

---

## 📱 User Experience Flows

### Waitlist Experience
1. **Discovery**: User finds waitlist signup (marketing, referral)
2. **Signup**: Clean, professional form with immediate feedback
3. **Confirmation**: Clear success state with expectations
4. **Launch**: Personal invitation when product goes live

### Free Trial Experience
1. **Invitation**: Professional email highlighting benefits
2. **Signup**: Compelling trial signup page with feature showcase
3. **Trial**: Dashboard with countdown banner and subscribe prompts
4. **Conversion**: Seamless upgrade path before/after trial ends

### Enhanced Prospect Experience
1. **Lead Generation**: Improved email with lead data tables
2. **Signup**: Professional pricing presentation
3. **Onboarding**: Immediate access to dashboard

---

## 🧪 A/B Testing Ready

### Template Variants
- Templates support `variant` parameter (`default`, `a`, `b`, etc.)
- Different subject lines, copy, CTAs can be tested
- Event tracking captures variant information

### Metrics Tracking
- Email opens, clicks, conversions tracked by variant
- Journey step progression analytics
- Template performance comparison

---

## 🔮 Future Enhancements

### Email Automation
- **Trial Reminders**: Automated emails at 7, 3, 1 days remaining
- **Drip Campaigns**: Multi-email sequences for each journey
- **Win-back**: Re-engagement for expired trials

### UI Enhancements
- **Progress Indicators**: Show journey step progression
- **Personalization**: Dynamic content based on user behavior
- **Social Proof**: Testimonials, usage stats

### Analytics Dashboard
- **Funnel Analytics**: Conversion rates by journey step
- **Template Performance**: Open rates, click rates by variant
- **Journey Optimization**: Identify drop-off points

---

## 📋 Implementation Checklist

### ✅ Completed
- [x] User model with journey fields
- [x] Jinja2 email template system
- [x] 6 customer journey API endpoints
- [x] Trial countdown banner component
- [x] Waitlist signup form component
- [x] 3 customer journey page components
- [x] Professional email templates (5 created)
- [x] App routing integration
- [x] Event tracking integration

### 🔄 Ready for Enhancement
- [ ] Trial reminder automation
- [ ] Email drip sequences
- [ ] A/B testing framework
- [ ] Journey analytics dashboard
- [ ] Social proof components
- [ ] Advanced personalization

---

**Summary**: The customer journey system provides a comprehensive, production-ready foundation for sophisticated user acquisition and conversion flows with professional design, robust error handling, and extensible architecture.
