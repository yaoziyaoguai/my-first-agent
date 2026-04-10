#!/bin/bash
echo "[Pre-commit] 正在检查待提交的 Python 文件..."

# 只检查暂存区里的 .py 文件
py_files=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$')

if [ -z "$py_files" ]; then
    echo "[Pre-commit] 没有 Python 文件需要检查"
    exit 0
fi

.venv/bin/ruff check $py_files
if [ $? -ne 0 ]; then
    echo "[Pre-commit] ❌ ruff 检查未通过，请修复后再提交"
    exit 1
fi

echo "[Pre-commit] ✅ 所有检查通过"
exit 0
