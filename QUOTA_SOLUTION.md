# Solution for Gemini API Quota Issues

## Problem
You're getting quota errors (429) because your Google Cloud project has free trial limits.

## Quick Solutions

### Option 1: Disable AI Temporarily (Recommended for Now)
The system has regex-based fallbacks that work without AI. To use them:

```bash
export DISABLE_GEMINI_AI=true
python manage.py runserver 0.0.0.0:8001
```

This will use regex-based detection instead of AI, which works well for most documents.

### Option 2: Activate Billing (If You Want AI)
1. Go to Google Cloud Console → Billing
2. Click "Activate billing" on your project
3. This will give you higher quotas

### Option 3: Wait for Quota Reset
- Daily quotas reset at midnight (your timezone)
- You can check quota status at: https://aistudio.google.com/usage?tab=rate-limit

## What the System Does Now

The system automatically:
1. ✅ Retries API calls up to 3 times with delays
2. ✅ Falls back to regex-based detection when quota errors occur
3. ✅ Works even when API is completely unavailable
4. ✅ Logs which detection method is being used

## Current API Key
- **New Key**: AIzaSyBRBA_VMMB1B0zzYuL4QJWUmRmTE90TsmI
- **Model**: gemini-2.5-flash

## Testing Without AI

To test the regex-only mode:
```bash
# Set environment variable
export DISABLE_GEMINI_AI=true

# Restart server
python manage.py runserver 0.0.0.0:8001
```

The system will work using regex patterns to detect:
- Document type
- Subjects
- Sections
- Question types

This is less accurate than AI but works reliably without quota limits.

