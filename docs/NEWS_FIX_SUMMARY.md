# News Function Fix Summary

## Problem
The `get_news()` function in `src/server/finance.py` was unable to read news data fetched from yfinance because the API response structure changed.

## Root Cause
yfinance recently updated its news API response format:

**Old format:**
```python
{
  "title": "...",
  "publisher": "...",
  "link": "...",
  "providerPublishTime": 1234567890  # Unix timestamp
}
```

**New format:**
```python
{
  "id": "...",
  "content": {
    "title": "...",
    "provider": {
      "displayName": "..."
    },
    "canonicalUrl": {
      "url": "..."
    },
    "pubDate": "2026-01-27T21:39:41Z"  # ISO 8601 string
  }
}
```

## Changes Made

### Modified: `src/server/finance.py:291-322`
Updated the `get_news()` function to handle the new nested structure:

1. **Data extraction**: Check for `content` key and fallback to root level
2. **Title**: Extract from `content.title`
3. **Publisher**: Extract from `content.provider.displayName`
4. **Link**: Try `canonicalUrl.url`, then `clickThroughUrl.url`, then fallback to `link`
5. **Date parsing**:
   - Primary: Parse ISO 8601 format from `pubDate` or `displayTime`
   - Fallback: Parse Unix timestamp from `providerPublishTime` (for backward compatibility)

## Testing
Created comprehensive test suite (`test_news_direct.py`) that validates:
- ✅ Basic news fetching (AAPL, TSLA)
- ✅ Invalid ticker handling
- ✅ Date filtering
- ✅ Invalid date format error handling
- ✅ All fields properly populated (title, publisher, link, date)

All tests pass successfully.

## Files Modified
- `src/server/finance.py` - Fixed news parsing logic (lines 291-322)

## Files Created (for testing)
- `test_yfinance_news.py` - Diagnostic test to identify API structure
- `test_news_direct.py` - Comprehensive test suite

## Backward Compatibility
The fix maintains backward compatibility by:
- Checking for both old and new field names
- Trying ISO 8601 date parsing first, falling back to Unix timestamps
- Gracefully handling missing fields with default values
