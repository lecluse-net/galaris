#!/usr/bin/env bash
set -euo pipefail

# Shared script: initializes SearXNG configuration in data/search/
# from default versioned files in resources/search/
# Used by bin/install.sh and make update

echo "🔍 Checking SearXNG configuration..."

mkdir -p data/search

for file in resources/search/*; do
    filename=$(basename "$file")
    if [ ! -f "data/search/$filename" ]; then
        if [ "$filename" = "settings.yml" ]; then
            search_secret=$(openssl rand -hex 32)
            sed "s/__GALARIS_SEARCH_SECRET__/${search_secret}/" "$file" > "data/search/$filename"
        else
            cp "$file" "data/search/$filename"
        fi
        echo "✅ data/search/$filename created from resources/search/"
    else
        echo "ℹ️  data/search/$filename already exists, keeping"
    fi
done

# Upgrade configurations created when SEARCH_SECRET_KEY was an environment
# variable. SearXNG owns this private secret; it is not an application setting.
if grep -qE '\$\{SEARCH_SECRET_KEY\}|__GALARIS_SEARCH_SECRET__' data/search/settings.yml; then
    search_secret=$(openssl rand -hex 32)
    sed -i \
        -e "s/\${SEARCH_SECRET_KEY}/${search_secret}/" \
        -e "s/__GALARIS_SEARCH_SECRET__/${search_secret}/" \
        data/search/settings.yml
    echo "✅ SearXNG private secret generated"
fi

echo "✅ SearXNG configuration checked"
