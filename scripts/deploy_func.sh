#!/bin/bash
set -e

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <function_app_name>"
  exit 1
fi

FUNC_APP="$1"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src"
FUNC_DIR="$ROOT_DIR/functions"

# Step 1: Build wheel for src package
cd "$SRC_DIR"
echo "Building wheel for src..."
python3 setup.py sdist bdist_wheel

# Step 2: Remove any previous wheel from functions dir
cd "$FUNC_DIR"
rm -f octopus2adls_shared-*.whl

# Step 3: Copy new wheel to functions dir
cp "$SRC_DIR"/dist/octopus2adls_shared-*.whl "$FUNC_DIR"/

# Step 4: Update requirements.txt to use only the new wheel
WHEEL_NAME=$(ls octopus2adls_shared-*.whl | head -n 1)
grep -v '^octopus2adls_shared$' requirements.txt | grep -v '^\./octopus2adls_shared-.*\.whl$' > requirements.txt.tmp
mv requirements.txt.tmp requirements.txt
echo "$WHEEL_NAME" >> requirements.txt

# Step 5: Test pip install locally
pip install --force-reinstall "$WHEEL_NAME"

# Step 6: Publish to Azure
func azure functionapp publish "$FUNC_APP"

echo "Deployment complete for $FUNC_APP"
