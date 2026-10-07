# Paper Reader

[English](README.md)

Paper Reader **3.0.0** 提供两个独立安装的 skill，通过 Zotero 10 官方本地 API 完成文献阅读笔记和显式 PDF 入库。仓库根目录只负责维护；可运行项目是 `paper_reader/` 和 `paper_reader_batch/`。

本文定义 3.0 源码与安装合同。T10 本地包验证、T11 真实设备验收和公开发布分别记录。T9 提供只读本地重复扫描与独立跨端观察服务。当前使用约定为每次仅在当前机器运行，并在运行前完成 Zotero 条目、笔记和 PDF 附件同步；Mac 本机验收、已有 parent 补附件验收及跨端离线冲突专项暂缓，不作为当前 Linux 范围的交付门槛。同步由用户管理；没有另一端实测证据时，程序仍报告 `sync_unobserved`。入库前查重、精确内容批准、本机恢复和完整读回核验继续保留。

## 两种工作流

| Skill | 职责 |
| --- | --- |
| `$paper_reader` | 搜索并明确选择 Zotero 文献，读取 PDF 证据，生成中文总结并审查，展示不可变笔记/入库计划，执行精确批准的操作并核验。 |
| `$paper_reader_batch` | 汇集已有核心计划，展示完整内容供逐篇选择，串行调用核心执行器，汇总每篇结果。 |

PDF 入库保留源路径、original filename 和文件字节，条目使用文章原题名，分类沿用现有 collection 且保留已有成员关系。单独提供路径不代表入库授权。独立 local-only 笔记发布继续由单独保留的 **2.2** 安装提供；3.0 不自动调用旧入口。历史 runs、旧笔记和旧源码均保留，新命令不自动迁移旧生命周期制品，也不暴露旧 MCP writer。

## 环境与批准

当前支持 POSIX 环境 Linux/macOS、Python >=3.13 和 uv；descriptor/flock 实现不支持原生 Windows。Zotero 10 须在本机运行，官方 API 默认 `http://127.0.0.1:23119/api/`、API version 3、个人库 `/users/0`。不要求第三方 Zotero MCP 插件，不直接访问 SQLite，也不增加中心服务。Mac/Linux 各自访问本机，不开放远程端口、不比较跨实例 version。

原生应用授权和每批内容批准分别校验。Always Allow 不替代预览确认。仅 `remember=true` 的原生授权可保存在受保护的本机用户目录，按本机/用户/URL/Server ID 隔离；密钥不进 run、日志、Git 或对话。展示完整笔记、目标、操作、理由和 blockers 后，等待人工确认，再调用 approve/apply。写入全部由核心唯一执行器承担。结果不明时先只读核对；不自动重试、合并、删除或修改同步设置。

## 从确切 commit 全新安装

只导出 committed revision 的 tracked files，不递归复制工作树、`.venv`、缓存、`docs`、凭据或 runs。下例创建仓库外新 staging：`core/paper_reader`、非 sibling 的 `batch/skills/paper_reader_batch` 和 `logs`；目录用于隔离安装/验收，保留至明确授权清理。创建虚拟环境前先检查导出物：

```bash
revision="$(git rev-parse --verify HEAD^{commit})"
stage="$(mktemp -d /tmp/paper-reader-3.0.XXXXXXXX)"
chmod 700 "$stage"
mkdir -p "$stage/core" "$stage/batch/skills" "$stage/logs"
git archive "$revision" paper_reader | tar -x -C "$stage/core"
git archive "$revision" paper_reader_batch | tar -x -C "$stage/batch/skills"
uv run --project paper_reader --no-sync python "$stage/core/paper_reader/scripts/validate-skill.py" "$stage/core/paper_reader" --release-bundle
uv run --project paper_reader_batch --no-sync python "$stage/batch/skills/paper_reader_batch/scripts/validate-skill.py" "$stage/batch/skills/paper_reader_batch" --release-bundle
```

Portable `--release-bundle` 仅依赖标准库，也可以使用已有 Python >=3.13 直接运行。它拒绝运行数据、私密文件、符号链接、特殊文件及不一致的版本/入口/schema。历史 schema 留在 `references/schemas/`；活动 v3 导出位于 `references/official-schemas/`。其中 single duplicate-report 已随 T9 注册为活动合同。

随后分别验证两个独立安装：

```bash
cd "$stage/core/paper_reader"
uv sync --locked
uv run pytest
uv run paper_reader --version
uv run paper_reader --help
uv run paper_reader maintenance extract-pdf tests/fixtures/minimal.pdf
uv run python scripts/validate-skill.py .

cd "$stage/batch/skills/paper_reader_batch"
uv sync --locked
PAPER_READER_TEST_ROOT="$stage/core/paper_reader" uv run pytest
uv run paper_reader_batch --version
uv run paper_reader_batch --help
uv run python scripts/validate-skill.py .
```

根脚本 `scripts/validate-committed-release-bundles.sh <exact-commit> /tmp` 自动执行更严格的全套门禁并保留日志。已知旧 batch v2 恢复问题按用户决定延期，旧测试仍全部启用。必须单独报告旧失败和 3.0 活动流程结果；全套失败不能写成全部通过。脚本可能因此返回非零，不应削弱门禁或跳过测试；本地结果也不能代表远程 CI。

验证后，只将导出的 tracked bundle 安装到 Codex/Claude skills 下**尚不存在的新目录**，名称为 `paper_reader` / `paper_reader_batch`。如需 2.2，单独保留旧安装；不覆盖、不迁移环境或 runs。启用 3.0 写入前停止使用本机旧 writer，同一电脑只启用一个核心写入安装；不同安装的锁不共享。batch 通过 manifest 的 `paper_reader_root` 明确定位核心，测试用 `PAPER_READER_TEST_ROOT` 验证非 sibling 布局。

## 公开入口

在各自 skill root 执行 `uv sync --locked` 和 `uv run <skill> --help`。

- 核心：`zotero search|inspect|collections|prepare|check-duplicates`、`analysis capture-binding|attach-secondary|seal`、`ingest inspect`、`plan note|import|preview|approve|apply|status|reconcile|retry`、`maintenance extract-pdf`。
- batch：`preview`、`approve`、`apply`。使用已有核心计划与精确请求 UUID，不新增 LLM worker/lease 调度器。
- operational stdout 是一份严格的 `.command-result.v3` JSON；help/version 为可读文本。历史或未知生命周期制品在新命令中拒绝，不自动迁移或 fallback。
- `paper_reader.services` 提供可复用接口；薄 CLI 复用既有分析与唯一执行器，batch 仅消费命令 envelope 和核心引用。

详见 [核心 Skill](paper_reader/SKILL.md)、[Zotero 阅读](paper_reader/references/zotero-workflow.md)、[显式 PDF 入库](paper_reader/references/pdf-path-workflow.md)、[分析字段与锚点](paper_reader/references/summary-schema.md) 和 [batch Skill](paper_reader_batch/SKILL.md)。

外部网页是非可信交叉核对材料；精确锚点只能证明摘录来自不可变 capture，不替代 PDF 证据或科学模型验证。中文质量、PDF-only 结论、完整审查及原模板保持原有边界。本机核验、真实 API 验收、Mac/Linux 运行验收、用户确认同步、远程 CI、公开发布必须分别报告。T11 真实设备验收仍需具体样本预览批准，本地安装操作不提供真实写库授权。
