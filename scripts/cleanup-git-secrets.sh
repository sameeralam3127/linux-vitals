#!/bin/bash
# Script to remove secrets from Git history
# This uses git-filter-repo to permanently remove .env files from all history

set -e

echo "🔐 Git History Secret Removal"
echo "=============================="
echo ""
echo "⚠️  WARNING: This will rewrite Git history!"
echo "⚠️  Anyone with clones will need to re-clone the repository."
echo ""
read -p "Continue? (type 'yes' to proceed): " -r
echo
if [[ ! $REPLY =~ ^yes$ ]]
then
    echo "Aborted."
    exit 1
fi

# Check if git-filter-repo is installed
if ! command -v git-filter-repo &> /dev/null; then
    echo "❌ git-filter-repo not found. Installing..."
    pip install git-filter-repo
fi

echo "📝 Removing .env files from Git history..."
git filter-repo --path .env --invert-paths --force

echo "✅ History cleaned. Now forcing push to remote..."
echo ""
echo "Run these commands to update your remote:"
echo "  git push origin --force-all"
echo "  git push origin --mirror --force"
echo ""
echo "Verify .env is removed from history:"
echo "  git log --all --full-history -- .env"
