# Mercury（墨墨）

在 `Mercury` 目录下执行（PowerShell）。

## 安装

```powershell
py -3.12 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Seed

```powershell
.\.venv\Scripts\python.exe -m mercury.seed
```

## 运行

```powershell
.\.venv\Scripts\python.exe -m mercury --user test_user_001
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```
