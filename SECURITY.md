# Security Policy

## Supported Versions

We actively support the following versions with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 5.0.x   | :white_check_mark: |
| < 5.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in MIRT AI, please follow these steps:

1. **Do NOT** create a public GitHub issue
2. Email security details to: [security@mirt.ai] (or create private security advisory)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Fix Timeline**: Depends on severity (typically 7-30 days)

## Security Best Practices

### For Developers

1. **Never commit secrets**:
   - API keys, tokens, passwords
   - Database credentials
   - Private keys

2. **Use environment variables** for all sensitive configuration

3. **Validate all user input**:
   - Use `input_sanitizer.py` for text sanitization
   - Validate metadata with Pydantic models
   - Check rate limits

4. **Keep dependencies updated**:
   - Run `pip list --outdated` regularly
   - Review security advisories (GitHub Dependabot)
   - Update critical dependencies promptly

5. **Review code changes**:
   - All PRs require review
   - Security-sensitive changes need additional review
   - Use pre-commit hooks

### For Deployment

1. **Use HTTPS** for all external communication
2. **Enable rate limiting** (Redis-based for production)
3. **Monitor logs** for suspicious activity
4. **Rotate secrets** regularly
5. **Use least privilege** for service accounts
6. **Enable RLS** (Row Level Security) in Supabase
7. **Keep infrastructure updated**

## Known Security Features

- ✅ Input sanitization (SQL injection, XSS, prompt injection)
- ✅ Rate limiting (Redis-based, distributed)
- ✅ Environment variable validation
- ✅ Secret masking in logs
- ✅ HTTPS enforcement
- ✅ Row Level Security (RLS) in database
- ✅ Circuit breakers for external APIs
- ✅ Retry logic with exponential backoff

## Security Checklist

Before deploying to production:

- [ ] All environment variables validated
- [ ] Secrets not in code or logs
- [ ] Rate limiting enabled
- [ ] HTTPS configured
- [ ] Database RLS policies active
- [ ] Dependencies updated and scanned
- [ ] Security headers configured
- [ ] Monitoring and alerting set up
- [ ] Backup and recovery tested

## Dependency Security

We use the following tools for dependency security:

- **Dependabot**: Automatic security updates
- **pip-audit**: Vulnerability scanning
- **Safety**: Python dependency checker

Run security checks:
```bash
pip install pip-audit safety
pip-audit
safety check
```

## Disclosure Policy

We follow responsible disclosure:

1. Reporter notifies us privately
2. We confirm and assess the vulnerability
3. We develop and test a fix
4. We release the fix and credit the reporter
5. We publish a security advisory

## Contact

For security concerns: [security@mirt.ai]

---

**Last Updated**: 2025-12-20

