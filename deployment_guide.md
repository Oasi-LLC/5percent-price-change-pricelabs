# Deployment Guide: Production to Cloud

## Important Rules
- NEVER merge branches directly (they have different .gitignore files)
- NEVER try to push all files from production to cloud
- ALWAYS respect the strict cloud .gitignore
- ALWAYS check what files will be pushed before pushing

## Step-by-Step Deployment Process

### 1. Backup Current Work (Optional)
```bash
# If you want to backup your current state
git add .
git commit -m "backup: Current state before deployment"
```

### 2. Ensure Clean State
```bash
# Check what branch you're on
git branch
# Should show you're on 'production'

# Check if you have uncommitted changes
git status
# Commit any changes you want to keep
```

### 3. Switch to Cloud Branch
```bash
# Switch to the cloud branch
git checkout prod_clean

# IMPORTANT: Verify you're on clean state
git status
# Should show "nothing to commit, working tree clean"
```

### 4. Copy ONLY Required Files
```bash
# DO NOT use git merge!
# Instead, copy only the specific files you updated
# Example:
cp ../production/app.py .
cp ../production/requirements.txt .
cp -r ../production/resources/ .

# Check what will be added
git status
# Should ONLY show the files you intentionally copied
```

### 5. Review Changes
```bash
# Review exactly what will be committed
git diff
# Make sure no unwanted files are included
```

### 6. Commit and Push
```bash
# Add only the specific files
git add app.py requirements.txt resources/

# Commit with clear message
git commit -m "update: Description of changes"

# Push to cloud
git push origin prod_clean
```

### 7. Return to Development
```bash
# Switch back to production branch
git checkout production
```

## Common Mistakes to Avoid
1. ❌ Don't use `git merge production` on prod_clean
2. ❌ Don't copy entire directories without checking contents
3. ❌ Don't push without checking git status
4. ❌ Don't modify .gitignore files during deployment

## Files That Should NEVER Be in Cloud
- data/
- tests_parsing/
- code_snapshot_system/
- full_code_snapshot.txt
- .env (use Streamlit secrets instead)
- Any development/testing files 