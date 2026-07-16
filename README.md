# EduExam Agent

项目的重要功能变化和当前阶段限制见 [更新日志](CHANGELOG.md)。

EduExam Agent 是面向教师的 Windows 桌面应用，用于在教材边界内推荐知识点、生成题目、组装试卷并导出答案解析。

## 当前状态

第一阶段基础工程已完成，并已加入题目综合评分规则，以及智能推荐、正式试卷和训练习题的范围/题型配置界面。课程、教材解析、真实模型调用与题库持久化仍将在后续阶段接入。

题目综合分采用百分制：题目质量占 70%，与目标难度的适配度占 30%。推荐功能可设置最低综合分，并按综合分从高到低选择题目。正式试卷与训练习题都支持整本教材、单章节和跨章节范围；训练习题不使用正式试卷格式，可自由组合选择、填空、计算和应用题。

## 技术栈

- Python 3.11/3.12
- PySide6
- SQLAlchemy 2.x + SQLite
- Pydantic 2.x
- pytest、Ruff

## 从零运行（Windows PowerShell）

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\run_dev.ps1
```

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

应用数据默认写入 `%APPDATA%\EduExamAgent`，不会写入安装目录。配置文件首次启动时由应用创建，敏感密钥不会写入普通配置文件。

## 架构

项目采用模块化单体与分层设计：`ui` 只负责交互；`application` 编排用例和 Agent 工作流；`domain` 保存业务规则；`infrastructure` 提供数据库、模型、检索、解析和导出适配器。高层逻辑通过接口依赖基础设施，便于替换模型服务、文件解析器和导出格式。

详见 [第一阶段架构说明](docs/architecture/phase-1-architecture.md)。
