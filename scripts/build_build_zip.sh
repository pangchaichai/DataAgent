#!/bin/bash
# 生成 DataAgent PyInstaller 构建包 (build.zip)
# 用法: bash scripts/build_build_zip.sh
# 输出: dist/DataAgent-v3.0-beta1-build.zip

set -e

cd "$(dirname "$0")/.."

BUNDLE_VERSION="v3.0-beta1"
OUTPUT="dist/DataAgent-${BUNDLE_VERSION}-build.zip"

echo "==> 清理旧包 ..."
rm -f "$OUTPUT"

echo "==> 打包源码 ..."
zip -r "$OUTPUT" . \
  -x ".git/*" ".claude/*" "__pycache__/*" "*.pyc" \
  -x ".pytest_cache/*" ".ruff_cache/*" ".coverage" \
  -x "dist/*" "docs/*" "tests/*" "testdata/*" \
  -x "data/uploads/*" "data/sessions/*" "data/outputs/*" \
  -x "data/compliance_audit/*" "data/logs/*" "data/skill_drafts/*" \
  -x "data/test_reports/*" "data/traces/*" \
  -x "*.zip" "*.egg-info/*" \
  -x "venv/*" ".venv/*"

echo ""
echo "==> 完成: $OUTPUT"
ls -lh "$OUTPUT"
