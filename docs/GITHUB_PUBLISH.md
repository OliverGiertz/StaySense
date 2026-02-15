# GitHub Publish Guide

## 1. Repository erstellen

- Neues GitHub Repo erstellen, z. B. `staysense-mvp`
- Private oder Public nach Bedarf

## 2. Remote setzen

```bash
cd StaySense
git remote add origin git@github.com:<ORG_OR_USER>/<REPO>.git
# alternativ HTTPS:
# git remote add origin https://github.com/<ORG_OR_USER>/<REPO>.git
```

## 3. Push

```bash
git push -u origin main
```

## 4. Empfohlene Repo-Settings

- Branch Protection fuer `main`
- Issues/Projects aktivieren
- Secrets fuer Deployment (falls CI/CD)
