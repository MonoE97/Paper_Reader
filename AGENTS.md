# AGENTS.md

## 规范适用范围与当前工作阶段

- 2026-10-07 用户更新使用前提：每次仅在当前机器运行，运行前确保已同步到最新状态；本轮按 Zotero 条目、笔记及 PDF 附件均已同步完成理解，Git 源码同步另行完成。跨端离线冲突/双端重复制造专项不再作为当前交付门槛；Mac 本机验收、已有 parent 补附件样本继续延期。保留 Server ID 隔离、入库前查重、精确内容批准、本机互斥、完整读回与不明结果恢复；用户同步保证不构成程序的 remote_observed 证据，也不修改现有运行时代码或同步设置。
- 本轮用户明确授权将当前改动本地提交并 push 到对应开发分支 `origin/docs/zotero-local-api-plan`；仅普通 push，不合并 main、不强推、不覆盖现有 Skill 安装、不公开发布。当前 Linux 收尾仍需区分正式使用的 Skill 安装、T9 真实只读扫描及 batch 真实小批次验收；已完成的单篇入库/笔记及新进程重放不重复制造对象。旧 v2 恢复问题与独立 local-only 3.0 重构保持延期，不扩大此次开发范围。
- 2026-10-07 用户明确恢复并授权原计划 T9，基线 `231bf33`，沿用当前功能分支；要求直接、可维护实现及 thermo-nuclear 审查。覆盖此前 T9 延期限制，仅实施只读本地库扫描、重复证据、独立远端观察与分层报告；T11 的 Mac/同步/双端真实验收仍待执行，旧 batch v2 恢复缺陷继续延期。无真实授权/写库、安装覆盖、同步配置变更、push 或发布。
- T9 目录及边界：`ingest/duplicates.py` 复用同一元数据比较规则，按题名/稳定标识索引筛选本地候选，仅候选 PDF 读取 SHA-256；不扫描元数据完全不同的全库 PDF。`official/sync_report.py` 保存只读扫描、远端观察及报告；`official/models.py` 保存严格观察合同。新 Zotero 阅读/入库工作流记录同一扫描报告，显式 `zotero check-duplicates` 可复查；不可见远端保持未知，本机不可读附件记录 unavailable，不当成缺失或同步失败。远端观察复用既有完整 readback 校验，绑定确切本地结果与另一 Server ID，不比较跨实例 version，不改写执行 journal。duplicate-report.v3 注册活动 schema；纯 SyncReport/RemoteObservation 作为服务结果，不另增运行状态机或存储层。已有 `.superpowers` 主题目录保存离线证据；本地 checkpoint 后新 `/tmp/paper-reader-t9-*` 仅作 committed 非 sibling 安装验证并保留。
- 2026-10-07 用户授权开始 T11，并确认本轮先做 Linux 单机真实验收；Mac 暂不可用，保留待验收，同步及双端重复检测继续暂缓，不恢复 T9。沿用当前功能分支，基线 `231bf33`，消费 T10 已验证的独立 3.0 安装。三类样本由用户指定：新 PDF、已有 parent 缺附件、已有 PDF 的文献笔记；先完成只读准备和精确内容预览，再取得各项真实写入批准，不把本条开发/验收授权当作业务批准。Mac 上 Zotero 是否关闭须据用户实际确认记录，不能从“暂不可用”推断关闭。
- T11 用户随后指定两项样本：`/home/user/Downloads/s41467-026-76505-4.pdf` 的显式入库，以及“材料设计与离子运输”中的 `Additive-assisted quasi-dry process enabling freestanding sulfide electrolyte films for all-solid-state batteries` 阅读笔记；已有 parent 补附件本轮暂不测试。Mac 上 Zotero 已开启但用户不进行操作，不将本次描述为另一端关闭的隔离验收，也不更改或推断其同步状态。用户查看最终预览后明确“批准两项”；两个计划已通过 3.0 唯一执行器完成 Linux 写入、完整读回与新进程同批准重放，均为 `local_verified` / `sync_unobserved`。父条目/附件为 `Q2HY7Q67` / `Z5FF7X2G`，新笔记 `BFIA5A6M` 属于 `CN49QTA2`；源 PDF 身份与 bytes 不变。此次授权范围完成，原 T11 全范围及 A1–A9 全面验收仍有延期项；未修改运行时代码。
- T11 复用既有 CLI、run store、唯一执行器及本主题 `.superpowers` 证据目录；原则上不新增运行时框架或验收状态机。实际运行数据仍按单篇安装的 `runs/YYYY-MM-DD/<run_id>/` 及稳定 `.paper_reader_official/` 约定保存；启用写入前核实本机只有一个活动写入口。只在本计划“执行与验收记录”记录非敏感证据索引、分层结论和未验收项。没有全部相应证据时，不宣称原 A1–A9 首期验收完成；不覆盖旧安装、不更改同步设置、不删除测试数据、不 push 或公开发布。
- 2026-10-07 用户授权实施 T10，并选择继续延期旧 batch v2 恢复问题：完整运行保留的测试，旧失败与 3.0 活动流程/独立安装结果分别报告，不删除测试、不新增 skip/xfail。基线 `a7ce3d5`，沿用当前功能分支。T9 暂缓，同步及同步后重复由用户管理；保留 T6 入库前查重和本地写入核验，不生成未经实测的 `remote_observed`。T11、真实授权/写库、安装覆盖、push 和公开发布不在本轮范围。
- T10 将两个 package、锁文件、公开 CLI、Skill/UI metadata 和安装合同统一为 3.0.0。核心入口为 `paper_reader.official_cli:app`，batch 为 `paper_reader_batch.official_workflow.cli:app`；旧 2.2 源码、测试、schema 与历史 run 保留，但不注册为 3.0 命令，也不自动迁移或回退。下文 2.2 合同仅约束旧安装与保留的历史运行模块。
- 3.0 公开核心命令为 `zotero search|inspect|collections|prepare|check-duplicates`、`analysis capture-binding|attach-secondary|seal`、`ingest inspect`、`plan note|import|preview|approve|apply|status|reconcile|retry` 和纯工具 `maintenance extract-pdf`；只将已有服务接入薄 CLI，不复制分析或写入状态机。batch 公开 `preview|approve|apply`，接收显式核心计划引用，沿用 T8 的选择与串行执行。独立 local-only 发布重构继续延期，路径输入不隐式授权入库；需要旧 local-only 工作流时使用保留的 2.2 安装。
- T10 采集入口显式使用 `--prepared`、`--run-root`、`--coordination-root`，与旧 `--plan` 互斥。`scripts/lib/secondary-v3-binding.mjs` 调用已安装核心的只读 `analysis capture-binding`，复用 PreparedPaper/evidence/source 校验后读取计划并核对 digest；原采集网络策略不变。`tests/official/test_public_secondary.py` 用合成 CDP 覆盖 prepare → capture → attach → seal，不访问真实网站。两套 release validator 均拒绝 `docs`/`.superpowers` scratch。
- T10 目录约定：`paper_reader/src/paper_reader/official_cli_support.py` 保存同一 v3 CLI 的 JSON/error/artifact 边界；`official_analysis_cli.py` 保存分析与只读维护命令。`tests/official/test_public_contract.py` 验证安装入口与完整分析路径；已有 docs/release 测试原地更新当前安装合同，历史行为测试继续保留。活动 schema 使用既有 `references/official-schemas/`，由 v3 exporter 导出实际支持的合同；T9 占位 duplicate-report 不列为活动 schema，旧导出文件保留为历史材料。本主题 `.superpowers` 保存测试/审查证据；仓库外新 staging 目录先记录用途再导出，不清理历史目录。

- 2026-10-07 用户授权实施 T8，沿用当前功能分支与已批准设计；T9–T11、真实授权/写库、双端同步及发布仍不在本轮范围。核心开发期 CLI 支持显式跨 run 批准引用，一次进程串行调用既有 `apply_plan`、共享一个 CredentialProvider；先校验全部引用、批准与 journal，再允许连接。batch 只拥有选择、调度请求及汇总，不复制核心写入状态机或解释核心制品 schema。公开 2.2 入口/版本/schema/模板不变。
- T8 目录约定：`paper_reader_batch/src/paper_reader_batch/official_workflow/` 保存开发期严格 envelope 合同、子进程适配、批量 driver 与报告；`paper_reader_batch/tests/official/` 只使用合成数据与显式非 sibling core root。核心 `official_batch.py` 保存多批准入口的本地 admission 和串行编排，写入仍全部经 `operations/executor.py`。运行日志与审查继续保存在本主题 ignored `.superpowers` 目录，不清理历史文件。
- T8 batch 运行目录必须显式提供且已存在：`manifest.json` 为不可变 plan 引用清单；`requests/<UUID>/intent.json` 固定请求 fingerprint、预览摘要和明确选择，`approvals/<序号>.json` 只记录核心批准引用，`result.json` 记录完整调度结果。文件均 no-replace，`.batch.lock` 复用现有互斥原语。`state.v3` / `report.v3` 是从核心结果派生的汇总，不拥有写入真相。相同 apply request 再调用只读查询/核对，不再次发起 apply；已开始但丢失返回的批准请求不自动重新批准。没有 v3 worker/lease 调度器，既有阅读流程提供核心 plans；全部排除返回空批准。T8 无自动重试或清理。
- T8 `paper_reader_batch/references/official-schemas/` 只保存五个显式 batch v3 开发期 schema，由 `scripts/export-v3-schemas.py` 导出；不加入 released v2 registry。开发入口是 `python -m paper_reader_batch.official_workflow.cli`，未来 T10 才注册公开命令。跨 run 批准的 wire envelope 为 `BoundApprovalRef`（继承 run root/run ID/artifact，额外绑定 plan ArtifactRef），没有额外授权语义。
- 2026-10-06 已确认 Zotero 官方本地 API 渐进重构方案。本节至“本地规划目录约定”定义新版本目标与开发纪律；后文“项目目标”及 Paper Reader 2.2 合同记录当前已发布行为，继续约束尚未迁移的 2.2 runtime。
- 2026-10-06 T1 已本地提交 `c33eb26`；用户随后明确授权执行 T2（官方 API 只读适配）和 T3（保留质量 gate 的分析核心）。本轮仍不接入公开 CLI，不修改包版本、已发布 v2 schema、模板、凭据或 Zotero 数据。T4–T11 不在本轮实施范围，不能把 T2/T3 完成描述为官方写入工作流可用。
- 2026-10-07 用户明确授权 T4，覆盖上条的历史范围限制：在当前功能分支继续实现不可变计划、纯预览和精确选择批准，沿用已批准设计；T5–T11 仍不实施。补充预分配 key 的只读存在性查询，不请求原生授权或真实写库，不修改公开 CLI、2.2 版本/schema、模板或凭据。
- 2026-10-07 用户进一步授权 T5：实现进程内原生授权适配、受批准约束的 note/create 执行器、持久恢复/显式零匹配重试和开发期 CLI。覆盖先前 T5 范围限制；T6–T11 仍不实施，真实授权和真实写库仍须具体预览确认。保留 2.2 public CLI/版本/schema/模板，不持久化凭据。
- 2026-10-07 用户授权 T6：PDF 识别证据、重复判断、现有分类与入库计划，以及开发期 ingest inspect / plan import；仅只读规划，T7–T11 不实施。沿用当前功能分支，优先复用既有提取、存储、预览与批准边界，不增加执行状态机或真实授权/写库。
- 2026-10-07 用户授权 T7：沿用 T6 计划和 T5 唯一执行器，实现条目/附件创建、分类并集、分阶段本地上传与读回恢复；覆盖先前 T7 限制。T8–T11 不实施，公开 2.2 CLI/版本/schema/模板保持不变。真实验收需具体预览确认；提供的 PDF 若上传，只能选择 CATL 下的已有子 collection，不自动创建分类。
- 2026-10-07 用户确认 T7 CATL 样本的精确预览后进行真实验收。Zotero 会将 Extra 中支持的 DOI/ISBN 行移入标准字段；创建读回允许这一无损字段移动，但标识符值必须逐字符一致、剩余 Extra 必须一致，缺失或冲突继续阻断。沿用原批准与操作记录只读核对已经创建的条目，不重建或跳过核验。
- 本地 API 的附件创建 JSON 需先写 `linkMode` 再写 `filename`，保持批准内容不变。已发送后被明确拒绝的操作仍允许只读 reconcile；零匹配后的再次发送继续要求独立的显式 retry 确认，不能靠更换 key、重建计划或手改 journal 绕过。
- T7 真实上传后的核对发现，列表的 `itemKey` 查询可能包含子项；key 存在性改用官方单条目 GET（同样包含回收站条目）。仅在当前 Server ID/API version 均通过检查的 404 时判为不存在，其他读错继续失败，不通过过滤列表猜测可用 key。
- 2026-10-07 用户明确授权修复官方 Local API 授权复用，覆盖此前“不持久化凭据”的开发范围限制；只处理认证，不改分类、命名、笔记或业务批准。先离线测试，不请求真实授权或写库。仅持久化原生响应 `remember=true` 的 key；按本机身份、当前用户、base URL 和实时 Server ID 隔离，Linux 使用 `~/.config/paper-reader/zotero-local/`，Mac 使用 `~/Library/Application Support/Paper Reader/zotero-local/`，不采用云盘/仓库/XDG 重定向。专用目录 0700、凭据文件 0600，拒绝符号链接与不安全权限；文件只保存当前实例授权或已失效的空记录，不进 Git、run、日志或聊天。`official/credentials.py` 独占加载/原子保存/失效；`auth.py` 先加载并复用持久 key，同一实例每个 provider 最多请求一次原生弹窗，一次性授权仅返回一次。只有认证写请求明确 401 才作废持久 key；403/412/429/超时保留原分类和恢复边界，不自动重发。诊断仅允许 has_key、remember、path、status 四字段，上传路径中的 uploadKey 必须隐藏；原有预览与精确批准仍是执行前提。真实连续操作/进程重启验收另需具体操作批准。
- 2026-10-06 用户另行授权修复全量回归发现的旧 v2 manifest 读取漏检：在同一已打开 descriptor 上有界复读并比较内容，保留现有身份/资源校验和错误码，不增加重试或新存储机制。
- 新版本目标与旧实现发生冲突时，允许在明确的新版本实现任务内更换 MCP-only、local-API-read-only、固定包划分和旧状态机等历史选择；不得通过这一优先级规则直接绕过现行 2.2 写入 gate，或给旧安装偷偷增加另一条写入路径。
- 通用纪律始终适用：Python 使用 uv；变更先更新规范再实现；保留历史数据；密钥不入代码、commit、日志或规划文件；不直接修改 Zotero SQLite、storage 元数据或 Better Notes 配置。删除、数据迁移、凭据配置、CI/CD、全局依赖、系统配置、push/rebase/reset-hard 和公开发布仍需用户明确授权。
- 功能实现必须区分离线测试、单机真实 API 验收、Mac/Linux 双端同步验收和发布验证；每类证据单独报告。没有实际观察到另一端数据与附件，不得报告同步成功。

## 已批准的新版本目标（尚未实现）

### 范围与结构

- 首期交付两类工作流：外部 PDF 的识别、分类、命名和 Zotero 入库；Zotero 文献的逐篇分析、预览和笔记写回。保留现有笔记内容、中文要求、模板、PDF 证据与外部交叉核对边界作为质量基线。
- 独立的文件路径 PDF 分析可延后重构，但后续必须在 Zotero 未运行或未安装时可用。首期 PDF 入库是显式操作，不能把路径输入隐式解释成入库授权；当前 2.2 local-only 路由在其版本内保持原义。
- 专题报告生成入库和实际 InoLab 接入不属于首期。分析、规划、执行与核验提供可复用的 Python 接口和结构化结果；首期不建立中心服务、额外 MCP server 或跨机在线依赖。
- 保留两个 skill 入口及当前安装方式作为首期起点。单篇核心独占 Zotero 适配、分析质量、写入计划、执行与核验；batch 只负责调度、选择和报告，通过明确 CLI 边界调用核心，不复制 schema、模板或恢复算法。
- Mac 与 Linux 各自访问本机 Zotero，保留用户现有同步设置。不得假设另一端在线，不远程暴露本地 API 端口，不比较不同实例的本地 version。

### 官方 API 与批准边界

- 新流程通过 Zotero 10 官方本地 API 读取和写入，默认 `http://127.0.0.1:23119/api/`、API version 3、个人库 `/users/0`。每次运行先读取 `Zotero-Server-ID`；实例变化后旧 snapshot、version 与批准不得沿用。不得硬编码历史 Server ID 或依赖第三方 MCP/SQLite fallback。
- Codex 负责识别、分析与提出理由；确定性工具负责校验、存储计划和执行。所有库内 mutation 都必须经过同一个受控执行器，不能由 agent 在批准流程之外直接调用 API。
- 预览必须覆盖具体文献、操作、目标、正文或字段变化、简短理由、重复证据与 blockers；完整笔记可检查。允许逐项排除后批量批准，批准绑定精确计划摘要与选中操作，不授权尚未生成的内容。
- 排除 parent 操作时，其依赖的附件或笔记操作不能执行。PDF 内容、目标、分类、正文、标签或其他批准内容发生实质变化时，受影响部分重新预览批准；未受影响项可独立继续。
- 原生 Zotero 应用授权与业务批准分别校验；“Always Allow”不替代每批内容批准。真实 API 写入与验收样本同样先展示具体预览再取得确认。密钥存储方式的改变不得夹带在普通代码实现中。

### 分类、命名与分析质量

- 新条目 `title` 使用文章原题名，不使用 PDF 文件名冒充题名。无法可靠识别元数据时进入待确认项，不编造字段。
- 分类沿用当前 Zotero collection；预览包含完整路径、key 和分类理由。首期不自动创建、重命名或重排分类体系，不覆盖已有 collection memberships。`CAiRS / Imaging`、`A78VFRQR` 仅为已知示例，不是全库默认分类或硬编码常量。
- PDF 附件首期保留输入文件名，并在预览中展示；文件名无法安全使用时先提出明确替代名重新确认。使用 Zotero 存储附件，保留源 PDF 的原路径、文件名和 bytes；不直接操作 Zotero storage。
- 阅读笔记沿用 `[Codex Summary] <article title> - YYYY-MM-DD` 及同日 `(v2)`、`(v3)` 后缀；新生成笔记作为子笔记创建，保留旧笔记。分析产物的既有命名约定保持其原有使用范围，不能当作入库 PDF 命名规则。
- 复用现有证据提取、中文 gate、sealed review、渲染与完整核验要求。首期不改进笔记内容体系，不修改 `templates/zotero_note.md.j2`；迁移后需用回归样例证明质量边界保留。

### 重复、恢复与同步

- 同一已批准操作重复执行必须返回已有结果；仅依赖 HTTP 返回值、进程内缓存或 Zotero 写入令牌不构成持久幂等。操作身份、批准内容、目标 key、发送前记录与核验结果必须持久化。
- 新任务再次遇到同一文献时，结合稳定标识、PDF 散列和元数据判断重复关系；题名相同只构成疑似重复，不自动合并。明确选中的 item key 与其快照必须同时核对。
- 条目创建、collection 更新、附件创建/上传/登记和笔记创建分别记录进度。部分成功不得整批重发；请求发送后崩溃、超时或响应丢失先进入结果不明状态，再只读核对。零匹配不能单凭一次查询解释为安全重试，多匹配必须阻断并交由用户确认。
- 同机操作串行化与互斥由执行器负责，batch 的调度 lease 不能成为另一套写入真相来源。锁与执行记录按当前实例和库隔离；跨进程重启仍须识别已发送和已完成的操作。
- 接受两端未同步时暂时产生重复。首期在后续运行/显式检查时检测同步后的疑似重复并输出证据，用户在 Zotero 中处理后再复查；不自动合并或删除，不承诺跨离线副本全局 exactly-once。
- 结果明确区分本地写入已核验、等待/尚未核实同步、远端实测可见、冲突待处理。不得从本地成功响应推断同步成功，也不以远端在线作为本地工作的前置条件。

## 本地规划目录约定

- `docs/` 继续是 `.gitignore` 覆盖的本地 scratch，不是公开文档树，不强制加入 Git，不改变 release bundle 的 tracked-file 边界。
- 新建 `docs/AGENTS.md` 先规定文档生命周期；`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` 保存设计，`docs/superpowers/plans/YYYY-MM-DD-<topic>.md` 保存可执行计划。两者必须标注批准来源、基线 commit、范围、未实现状态与相互链接。
- 计划必须列明具体文件、接口、依赖顺序、失败用例、验证命令和真实验收条件。沿用既有文件时先核对当前实现；新目录先补结构约定，不能因计划里出现路径就直接创建未定义的运行目录。
- 规划文件允许同主题修订并记录状态；不自动清理、覆盖别的主题、移动或删除历史材料。任何清理按用户删除红线单独授权。
- 只更新本规范和本地规划时，运行两套 `tests/test_default_workflow_docs.py`、两套 portable validator 与 `git diff --check`；不为文档变更新增 runtime 测试或执行真实 Zotero 写入。若修改运行时，继续按后文运行对应 full pytest、CLI 与 PDF smoke。

## 项目目标

本项目维护两个自包含 skill source：`paper_reader/` 和 `paper_reader_batch/`。3.0 从确切 committed revision 导出各自 tracked files，经 portable release 检查后在全新独立目录安装，支持非 sibling 布局。核心负责 Zotero 官方 API 阅读/显式 PDF 入库、质量 gate、计划/批准及唯一执行器；batch 只调度已有核心计划并汇总。旧 2.2 的独立 local-only 工作流可在保留安装中使用，不由 3.0 自动回退。根目录只承担维护文档、发布说明和本地规划记录。

## Paper Reader 3.0 安装与验证合同

- `paper_reader_batch/tests/legacy_core_fixture.py` 仅为保留的 v2 coordinator 及依赖它的 pre-recovery 测试复制显式核心根的源码/资源到 pytest 临时目录，将该测试安装的 console script 指向保留的 `public_cli`，locked/offline 安装后通过测试专用 `PAPER_READER_LEGACY_TEST_ROOT` 传给其子进程。不修改生产 v2 执行器、不改变 3.0 入口、不跳过测试；夹具无 Git、真实 run/凭据或环境拷贝，不自动清理验收目录。
- 两个版本均为 3.0.0；活动 CLI/schema/Skill/UI metadata 与锁文件一致。公开命令见本文件顶部 T10 范围。
- 核心活动 v3 schema 为 run、summary、review、review-package、candidate、identification-proposal、zotero-plan、zotero-approval、zotero-event、zotero-result、duplicate-report、command-result；batch 为 manifest、state、event、report、command-result。T9 实施时导出并注册 duplicate-report.v3，保留 `.v2` 历史 schema，不迁移旧 run。
- 3.0 继续执行下文通用 Git、数据保护、验证与 portable release 原则；凡提及 2.2/v2 public CLI、MCP-only writer、旧 lease/worker 协议的段落仅为历史合同，不约束已明确替换的 3.0 入口。
- 两套完整 pytest 均运行；旧 v2 恢复失败按用户选项 1 继续延期并逐项报告。活动 v3、当前 docs/release、portable validator、locked sync、help/version、PDF smoke、committed 非 sibling 安装必须有单独通过证据。不得把未通过的全套回归报告为 GREEN。

## Paper Reader 2.2 历史约束（仅保留模块及旧安装适用）

本文件定义 Paper Reader 2.2 的 released runtime contract。两个独立 package 的版本均为 `2.2.0`；public README、`SKILL.md`、UI metadata、JSON Schema、grouped CLI 与 lockfile 必须同步反映同一个已发布合同。Schema identifier 继续使用 `.v2`，不引入 V1 fallback、schema guessing 或自动迁移。

### Breaking 规则

- `paper_reader` 的活动 schema 只能是 `paper_reader.run.v2`、`paper_reader.summary.v2`、`paper_reader.review.v2`、`paper_reader.review-package.v2`、`paper_reader.candidate.v2`、`paper_reader.write-authorization.v2`、`paper_reader.verification.v2`、`paper_reader.reconciliation.v2` 和 `paper_reader.command-result.v2`。
- `paper_reader_batch` 的活动 schema 只能是 `paper_reader_batch.manifest.v2`、`paper_reader_batch.state.v2`、`paper_reader_batch.event.v2`、`paper_reader_batch.worker-result.v2`、`paper_reader_batch.local-prepare-result.v2`、`paper_reader_batch.write-result.v2`、`paper_reader_batch.reconciliation.v2`、`paper_reader_batch.report.v2` 和 `paper_reader_batch.command-result.v2`。
- 所有 V2 模型使用 Pydantic v2 strict mode 与 `extra=forbid`；不接受未知字段、隐式类型转换或模糊 schema。
- V1/unversioned artifacts are historical-only。它们只能作为不可变历史证据存在；V2 loader 必须在加锁、写文件、分配输出、网络调用或任何其他 mutation 之前以结构化错误码 `unsupported_run_schema` 拒绝 V1、无版本和未知版本。
- There are no aliases, migration loaders, dual readers, schema guessing, compatibility shims or hidden V1 fallbacks。V1 runtime surface has been removed；active source tree 只保留 V2 runtime，以及用于证明历史 schema 被只读拒绝的测试。
- 所有 operational commands 的 stdout 必须恰好是一份对应的 `*.command-result.v2` JSON；诊断写 stderr。`--help` 和 `--version` 可保持 human-oriented。

### Grouped CLI

`paper_reader` public grouped CLI 只包含：

- `route`
- `run init-local|init-zotero|prepare|status|validate`
- `review validate|seal`
- `candidate build`
- `local publish`
- `zotero authorize|verify|reconcile`
- `maintenance`，只承接与核心状态机无关的纯工具

`paper_reader_batch` public grouped CLI 只包含：

- `manifest ...`
- `run init|validate|status|recover|report`
- `worker claim|prompt|renew|finish|release|retry`
- `local-prepare claim|renew|finish|release|run`
- `write claim|preview|renew|release|begin|commit|mark-uncertain|reconcile|retry`

所有 batch state mutation 都必须带 `--request-id UUID`，并通过 request fingerprint 提供幂等 replay；相同 request id 只允许重放相同请求，不允许代表另一项操作。

### Immutable candidate 与 authorization

- Evidence、sealed review package、candidate 和 authorization 都是 immutable artifacts；任何输入、目标、正文、标签或 hash 改变都必须重建后继 artifact，禁止原地修补。
- 单篇 run 的 deterministic ownership 必须使用 `authorizations/<authorization_id>.json`、`verifications/<authorization_id>/<note_key>.json` 和 `reconciliations/<authorization_id>.json`；snapshot sidecar 可使用对应无 `.json` 的同 stem 目录，但 main artifact 必须最后发布并通过持续打开的 no-follow parent fd 完成 no-replace，禁止中间 symlink、hardlink 或检查后 pathname race 逃逸 run root。
- Candidate 必须绑定 run、source identity、evidence、sealed review、固定输出目标或 Zotero parent、精确 note title/tags/content，以及所有相关 artifact 的 canonical SHA-256 与 size。Zotero title 中的 Markdown 元字符必须在 `note.md` H1 中按字面量转义，并用与 single lock 完全相同的 Markdown renderer 生成 `note.html`；渲染后可见 H1、candidate title、authorization title 与 readback title 必须逐字符一致。
- `local publish` 只能把 local candidate 发布到 candidate 已固定的目标，使用 same-filesystem atomic no-replace；目标已占用时停止并 rebuild candidate，禁止覆盖或换目标继续发布。Local candidates 绝不产生 Zotero authorization。
- `zotero authorize` 不接受 parent/title/content/tag override；它必须重新计算所有 hash，刷新只读 parent/children snapshot，检查 parent fingerprint 与 title availability，并在本地 parent lease 下创建一次性 immutable authorization。Direct single-paper authorize 不传 batch identity options；命令必须在同一 atomic authorization transaction 内分别生成两个不可变 `direct_<uuid>` 作为 external claim identity 与 attempt identity，持久化到 authorization 并在 command result 返回，调用者不得自造或覆盖。Batch path 的 `--external-claim-id` 与 `--write-attempt-id` 仅 batch authorize 使用，both batch identity options must appear together，partial input 在 mutation 前拒绝，并绑定 batch claim + candidate digest；batch path 不生成 direct identity。TTL 默认且最大均为 300 seconds，authorization 绑定 random nonce/token、exact HTML、canonical HTML hash/length、tags、candidate digest、parent snapshot、external claim id 和 `write_attempt_id`。Authorization 不绑定 batch `lease_token`；lease 可独立 renew，batch begin 另行校验当前 lease。
- The external agent is the only Zotero writer。它只能按 authorization 的精确 MCP envelope 调用 MCP `write_note` / `write_note(action="create", ...)` at most once。CLI 与 batch runtime must not call `write_note`。
- `zotero verify` 强校验 parent、note key、exact title、完整 tag set、required headings、minimum length 和 canonical HTML hash。An exact parent + title + canonical HTML hash match locates one note but does not verify it。`zotero reconcile` 定位唯一 note 后仍必须对该 note 执行完整 verify；只有全部字段通过才可 verified。Zero -> not found 且需要显式 retry confirmation，many -> ambiguous/blocked。过期 authorization 仍可用于 verify/reconcile，但绝不能再次写入。

### Batch journal 与 lease

- `events/<20-digit-seq>.json` append-only hash-chain 是唯一 source of truth；`state.json` 只是 reconstructable snapshot。任何 gap、hash mismatch 或非法 event 都返回 `journal_corrupt` 并禁止 mutation。
- Event 的完整 `.writing` / digest `.tmp` 只表示 provisional intent，绝不进入 reducer truth；只有 originating request 可在 committed-prefix state 上完成 final source/closure/freshness precommit validation 后原子提升为 `<20-digit-seq>.json`。任何 proposal 在 staging 前必须证明自身与派生 abort marker 都不超过 JSON artifact limit。校验失败时，必须先在原 proposal 的同一 sequence 以 no-replace + parent `fsync` 提交 deterministic `request.aborted` no-op marker；marker 内嵌并 hash 绑定原 proposal 的 canonical event、request id、command 与 fingerprint，主 journal 因而永久返回 `request_aborted`。Loader 必须以单次顺序 prefix replay 校验 marker 内嵌 proposal 的 command、request/event identity、domain identity 与 reducer legality，pending marker 也必须在 promotion 前通过同一校验。原 proposal staging 只能在 marker committed 后成为 exact inert residue，并通过 held no-follow descriptor 清空为 zero-byte logical tombstone；exact aborted origin 可在返回 `request_aborted` 前只清理与自身 canonical event digest 绑定的 residue，其他请求只有通过完整 pre-recovery/pre-mutation closure 后才可做该内部清理，任何被拒绝的 unrelated request 必须保持 residue bytes/mtime 不变。无法解析为完整 pending event 的 current-next `.writing` 同样不是事实源：通过全部 live closure 的新 transaction 必须在自身 staging/commit 前以 held descriptor 将 exact inode/raw 清空并 reload，校验失败的请求不得触碰它。任何 `.aborted.*` sidecar 都不是事实源；event/transition namespace 必须在 materialize/sort 前有界枚举，staging/residue 数量与 aggregate reads 必须有硬上限，committed event canonical bytes aggregate 上限固定为 256 MiB。新 transaction 在任何 side effect 前必须为 proposal tombstone 与 abort marker 预留两个 event-directory entries；已有 pending proposal 在 promotion/recovery 前必须重新校验 marker entry 与 committed-byte headroom。唯一的非空 exact marker prefix `.writing` 必须在 held inode 上续写、`fsync` 并提升，禁止另建 marker 后遗留 partial entry。Final event rename 之后只允许 structural guard，禁止用时钟或外部 closure 反判已经 committed 的 event。
- `state.json` repair transition 必须同时绑定 manifest、journal head、old/new SHA-256 与 size，并用 `.run.lock` secret HMAC；invalid/noncanonical V2 snapshot 的 exchange/retired-leaf crash 必须可恢复，V1/unversioned/unknown snapshot 仍在 mutation 前只读拒绝。
- 每次 transaction 在 `.run.lock` 下校验 manifest SHA、journal、request id/fingerprint 与 lease token，按 durable atomic ordering 写 content-addressed result、event，再替换 snapshot。Named `.lock` 在 POSIX 上必须先持有 lock parent 的稳定 ancestor guard，再 flock parent directory 与 named inode，防止 lock 或整个 parent pathname replacement 形成第二个临界区；需要跨 coordinator crash 延续原子边界时，child 必须继承 named + parent + ancestor descriptor bundle 到 durable marker 发布完成。Stale snapshot 必须 replay journal；orphan result 必须忽略。
- Manifest builder 与默认 `run init` 尚未拥有 run journal 时，必须使用 skill-root 内、受全局 no-follow lock 保护的持久化 request receipt；receipt 先绑定 exact UUID、request fingerprint 与预留目标，crash/replay 只能恢复该 exact target，禁止扫描 runs 猜测。任何 output 首次发布前必须用实际 JSON artifact limit 同时预检 output、reserved receipt 与 committed receipt 的 canonical bytes；任一超限必须在 receipt/target publication 前以 `resource_limit` 只读失败，同 request 重试不得退化为 `receipt_corrupt`。
- Worker 与 local-prepare lease 默认 900 seconds。Worker 支持 claim/prompt/renew/finish/release/retry；`worker prompt` 只读且不 dispatch LLM。Local-prepare 支持 claim/renew/finish/release/run；`local-prepare run` 只可通过显式 `--paper-reader-root` 调用 V2 grouped local init/prepare，不 import 单篇 package、不做 LLM/Zotero 工作。每个 worker/local-prepare claim event 至多绑定一个 PDF；worker 可在同一 limit 内跳过后续 PDF 并用非 PDF item 填满，其余 PDF 通过独立 claim 获得并发。Worker claim/prompt/renew/finish 与 local-prepare claim/run/finish 必须在各自副作用前重新绑定当前 PDF path、size、SHA-256、device 和 inode；stale lease token / source drift 必须拒绝。Worker failed/blocked 只可显式 retry，local prepare failed 只可用新 request id/new attempt 显式 run，同一 resolved PDF 必须保持 same-PDF mutual exclusion。
- `local-prepare run` 的内部协调状态固定在 `results/local-prepare/.coordination/.attempts/<attempt_id>.json` 与 `results/local-prepare/.coordination/<request_id>/{coordinator.lock,record.json,init.started,init.stdout,prepare.started,prepare.stdout}`；`*.started` 只在对应 child 真正启动后出现。Record 先发布，HMAC attempt owner 绑定 request-directory device/inode；在任何 child reservation/spawn 前，还必须用 derived internal request id 提交 `local_prepare.coordination_reserved` journal event，把 external request/fingerprint 与该目录 identity 锚定进 source of truth。Journal binding 已存在时，整个 coordination tree、owner、record 或目录 identity 的缺失/替换只能 fail closed，禁止重建。Child launcher 必须先核对目录 identity、fork gated executor，再原子发布 HMAC started marker，最后放行 exact argv；supervisor 在 marker 前崩溃时 executor 只读确认 marker 缺失并退出，marker 后崩溃时 executor 仍执行一次。Reservation 之后、runner spawn 之前必须在 authoritative run lock 内再次校验 PDF path/bytes/device/inode 与完整 `paper_reader_root` identity。Child 继承 `.run.lock` descriptor bundle、stdout flock 与 child-owned timeout；仅 reservation、没有 started/stdout 的崩溃可安全重试，started 但无 strict stdout 是 `coordination_uncertain` 且禁止二发。Init timeout 固定 60 seconds，prepare 默认 600 seconds；首次 side effect 前剩余 lease 至少为 `60 + prepare_timeout + 60` seconds，prepare 前至少为 `prepare_timeout + 60` seconds。Expired local attempt 若无 execution marker 才可 requeue；已有/无法排除 execution side effect 时 `run recover` 必须续租同一 claim/attempt 供恢复，绝不能分配 attempt 2。
- Worker/local release 只允许在外部 side effect 与单篇 artifact 产生前，并必须显式 `--acknowledge-no-side-effects`；缺少确认、已有 result 或 identity 过期时只读拒绝，不能把可能已执行的工作重新排队。
- Write claim 每次只返回一个 candidate，并生成绑定 writer/item 的 `claim_id`、`lease_token` 与 `write_attempt_id`；lease 默认 120 seconds。固定顺序是 claim -> preview immutable candidate（此时 authorization 尚不存在）-> 展示目标并取得用户 explicit real-write intent -> external agent 调 single `$paper_reader zotero authorize`，authorization 只绑定 external claim id + candidate digest + `write_attempt_id` -> batch `write begin` 独立校验当前 `claim_id`、`lease_token`、`write_attempt_id` 与 candidate digest。Begin 要求 authorization 至少剩余 30 seconds，并在返回精确 MCP envelope 前原子消费 nonce、提交 `write.started`。同 request id 只返回 `replayed=true`，不得再次发送；新 request id 也不能创建第二次 start。
- 所有 write preview/renew/release/begin/commit/mark-uncertain 命令，以及对应 journal events 和 content-addressed results，都必须绑定同一 `claim_id`、`lease_token` 与 `write_attempt_id`；stale 或 cross-attempt identity 在 mutation 前拒绝。
- Write 状态为 queued -> claimed -> started -> written。Claimed release/expiry 可回 queued；started 后的 crash、error 或 expiry 必须进入 uncertain, never queued。`run recover` 在 `.run.lock` 内检测 exact `write_attempt_id` 的 `write.started` lease expiry，并追加唯一 `write.lease_expired_uncertain` event；expired token 不作为输入，同 recover request id 幂等 replay，该 attempt 不得回 queued 或再次 begin。`write mark-uncertain` 仅接受未过期 exact writer/claim/token/write-attempt identity，用于主动报告已知异常。只读 reconcile 的 parent + title + hash 唯一匹配只定位 note；该 note 完成 exact parent、note key、exact title、complete tags、required headings、minimum length 和 canonical hash 全量验证后才可 written。零匹配要求 `--acknowledge-no-match` 后以新 authorization/new request id retry，多匹配必须 blocked。
- Reducer priority 固定为 corrupt > write_uncertain > running > needs_attention > awaiting_write > ready > succeeded。Local PDF 不进入 write queue；全本地 batch 的 `effective_write_policy=local_only`。Batch report 保留从单篇笔记 `30 秒结论` 提取、再 fallback 到 `tldr` / `one_sentence_summary` 的规则。
- Batch worker success 必须绑定 sealed single-paper review package，并证明所有 fallback 展开后的实际 rendered note 已通过 Chinese-first gate；只有 candidate path 不足以记录成功。

### Secondary finding anchor

- 新建 Zotero run 的 immutable `source/secondary-plan.json` 必须显式写入 `finding_anchor_policy: "codepoint_sha256_v1"`，无论 eligible URL 数量是否为零。历史 V2 plan 缺少该字段时保持原 canonical bytes 与 legacy no-anchor 语义；不得按包版本、时间或 Summary 内容猜测、补写或迁移 policy。未知 policy、未知字段和非严格类型继续失败关闭。
- `paper_reader.summary.v2.secondary_cross_checks[].findings[]` 可新增至多一个可选 `anchor`，其精确形状为 `capture_sha256`、`start_codepoint`、`end_codepoint`、`excerpt_sha256`。两个 digest 都必须是小写 SHA-256；offset 必须是 strict integer，按 immutable capture `text` 的 Unicode code point 索引；区间为左闭右开，长度只能为 20–2,000 code points。不得存储 URL、标题、发布者或正文副本。
- `codepoint_sha256_v1` plan 下，每个 `status="used"` finding 必须恰好绑定一个 anchor；anchor 的 `capture_sha256` 必须同时等于 evidence ArtifactRef、secondary inventory 和 immutable capture member raw bytes 的 SHA-256，`excerpt_sha256` 必须等于 `sha256(capture.text[start_codepoint:end_codepoint].encode("utf-8"))`。计算前禁止 Unicode、换行或空白规范化。legacy plan 禁止任何 anchor。
- Resolver 必须在任何 projection 前一次性验证所有 assessment/anchor；任一缺失、错配、越界或 hash 错误都阻断 review sealing 与 candidate build，不得产生部分投影。渲染仍只显示现有带来源交叉核对标注，不显示 excerpt、offset 或 hash，也不修改 Summary。
- `30 秒结论`、一句话总结、论文背景/方法/贡献、作者明示局限与全部 canonical locator 继续保持 PDF-only；`evidence_summary` 不得引用 secondary locator。`templates/zotero_note.md.j2` 必须逐字节不变。
- Local PDF 与 local batch 不产生或消费 secondary plan/anchor。Batch 不解析、验证或复制 anchor 语义，只要求 `$paper_reader` 返回 sealed 单篇制品并校验其 opaque hash closure。
- raw-CDP 对无效 request URL 的新增信息只能是固定、有界、隐私保护的诊断分类：checkpoint、allow-listed resource-type class、value type、length bucket、parseability 与 `http|https|other|none` scheme class。不得把 raw URL、host、path 或 query 写入 artifact、stdout 或 stderr；分类不得放宽既有 request policy，Fetch cancellation 未确认仍为 fatal。

## 目录约定

- `paper_reader/src/paper_reader/official/`：新流程的实例/库身份、快照与 gateway/凭据 Protocol；T2 增加只读 HTTP 与附件定位，T5 增加进程内原生授权及执行器专用 note/create 请求。
- `paper_reader/src/paper_reader/analysis/`：v3 分析合同、prepare/review、共享 quality/rendering 与 evidence 存储适配；Summary/Review 与 v2 共享字段和校验，版本判别保持独立。内部 evidence/secondary 值格式复用现有构造器和校验器，只消费本次新构造且由 v3 manifest 绑定的 bytes，不读取历史 v2 run 或提供 fallback。`attach_secondary_captures` 以已有 PreparedPaper 的 run/source/plan 为输入，生成新证据和 PreparedPaper，保留旧制品；多 PDF 必须显式 attachment_key，分析核心不自行联网。
- `paper_reader/src/paper_reader/operations/`：v3 计划、批准、事件、结果及唯一文件存储实现；不接入现行 2.2 writer。T4 的 `planner.py` 复用 analysis/evidence.py 的 prepared/evidence 绑定校验，核对 candidate 闭包和实时只读前态；附件使用证据 metadata 中明确的 pdf_attachment_key，不遍历未选附件，`preview.py` 只投影计划并记录批准；制品引用路径由 store 的纯引用函数统一生成。计划记录 subject 题名、前态引用、完整 HTML、Markdown/HTML 内容引用及输入摘要。批准只接受非空、无重复且依赖闭合的明确选择，blocker 只阻断被选项；全部排除时无需生成批准。
- T5 的 `executor.py` 拥有批准校验和唯一发送路径，`reconcile.py` 拥有只读定位与完整笔记核验，`execution_state.py` 拥有事件合法性、结果投影与恢复状态。每条执行事件绑定 immutable approval；库锁内的 operation 索引仅绑定 run/plan，不保存第二份执行状态。`official/auth.py` 管理原生授权会话，后续获批的 `official/credentials.py` 补充 remember=true 的本机持久复用；拒绝/401/429 不在当前会话自动重复请求。`official_cli.py` 仅供开发期显式调用，要求调用者提供现有 run root 与 coordination root，不注册到公开 2.2 CLI。重试仅创建新 attempt，后续显式 apply 才能发送。
- `paper_reader/src/paper_reader/ingest/`：入库识别提案合同；T1 不实现识别、分类或上传。
- T6 的 `identify.py` 复用 PDF extractor，提供带源指纹的逐页证据与候选字段；目录检查逐项报告非 PDF、重复路径和源错误，不递归展开子目录。`duplicates.py` 只比较显式快照与只读获取的附件指纹，不依赖数据库或持久缓存；`planner.py` 拥有提案证据校验、分类完整路径、精确操作依赖与 freshness 校验。无操作的待确认/已存在结果仍保留入库预览，不伪造可批准操作；T5 执行器继续只接受 note。用户已选择：提案必须显式提供 item_type，无法可靠判断则阻断该篇；查重限定元数据候选及其本地 PDF SHA-256，预览明确这一覆盖范围，不扫描全库附件。提案可绑定用户明确选择的 parent/key/快照（仍不覆盖元数据冲突）以及不安全原文件名的明确替代名；外部字段证据使用含 URL、原文、PDF 指纹与对照理由的只读记录，原题名仍需 PDF 原文。标识符证据必须绑定具体值，并显式声明 self/citation/unresolved；工具核对精确引用和绑定，不从物理页码推断“本文 DOI”，不宣称自动语义识别。
- `paper_reader/tests/official/`：新合同和存储的合成离线测试，不访问真实 Zotero。
- T7 的 `ingest/upload.py` 只负责受批准上传的三个阶段；`ingest/execution.py` 负责入库操作绑定、前态与结果核验，`official/uploads.py` 负责本地上传协议。它们由 `operations/executor.py` 调度，复用唯一 journal/锁，不另设状态存储。上传许可和回执是内存类型，handle 不进入制品或错误；源文件通过既有 held source guard 读取。已完成前驱的 readback 提供后继前态，外部编辑仍须重新预览；登记发送后不明必须只读核对并显式重试，未登记且前态未变的传输可重新获取许可。
- `paper_reader/references/official-schemas/`：由 `scripts/export-v3-schemas.py` 生成的未发布 v3 schema；与现行 `references/schemas/` 的 v2 命名空间隔离。重新导出只更新登记文件，不自动删除。
- v3 `FileRunStore` 绑定调用者提供的已存在 run root；只分配摘要命名的 immutable artifacts 和 `operations/<operation_id>/events/<20-digit-seq>.json`。raw bytes 按 source/evidence/review/note/preview/readback 分类；事件目录只有完整连续且 hash 相连的 committed JSON 是事实源，不从临时残留恢复执行。资源上限复用现行 `resource_policy.py`；不新增数据库或可写状态快照。
- v3 实例/库锁使用调用者显式指定的 coordination root，按 Server ID/library identity 摘要隔离；不猜 skill 祖先。其 parent 必须是已存在且运行期间稳定的安装目录，构造 store 时只读绑定 identity，持锁时先独占该 parent，再打开实例/库目录，防止锁目录替换形成第二个临界区。首期保守地串行化同一安装内各库，不承诺跨库并行；调用者不得在执行期间更换安装目录。T5 的 `operations/<operation_id>.json` 索引绑定唯一 run/plan；有执行 journal 时索引缺失不重建。`.paper_reader_official/` 是忽略的本机状态，保留历史，不自动清理；默认安装入口仍待 T10。
- `.superpowers/sdd/<plan-basename>/`：本计划执行 ledger、任务摘录、测试日志与审查记录；不提交、不自动清理，不替代 docs 中的设计与计划。
- `paper_reader/SKILL.md`: skill 入口，只保留触发、路由和核心安全边界。
- `paper_reader/agents/openai.yaml`: Codex UI metadata；更新 `SKILL.md` 后检查是否同步。
- `paper_reader/src/paper_reader/`: Python package code for deterministic CLI/tooling logic.
- `paper_reader/tests/`: pytest tests; never perform real Zotero writes.
- `paper_reader/templates/`: Jinja2 note template.
- `paper_reader/references/`: workflow and schema references loaded by the skill when needed.
- `paper_reader/scripts/`: bundled helper scripts, including portable skill validation。T3 抽取共享分析函数后，validator 显式登记新子包依赖；release closure 测试按实际模块/包路径核对，不切换 2.2 版本或公开 CLI。
- `paper_reader/pyproject.toml` and `paper_reader/uv.lock`: dependency and lock metadata for the installed skill root.
- `paper_reader_batch/SKILL.md`: batch skill 入口，只保留批量触发、路由和 Zotero write-through 安全边界。
- `paper_reader_batch/agents/openai.yaml`: Codex UI metadata for `paper_reader_batch`。
- `paper_reader_batch/src/paper_reader_batch/`: deterministic batch CLI/tooling logic，包括 manifest、state、takeaway extraction 和 report。
- `paper_reader_batch/tests/`: pytest tests; never perform real Zotero writes or real LLM dispatch.
- `paper_reader_batch/references/`: batch workflow reference loaded by the skill when needed.
- `paper_reader_batch/scripts/`: bundled helper scripts, including portable batch skill validation.
- `paper_reader_batch/pyproject.toml` and `paper_reader_batch/uv.lock`: dependency and lock metadata for the installed batch skill root.
- `README.md`: English public entry point; explain install from `paper_reader/`, not root runtime usage.
- `README.zh-CN.md`: Chinese README paired with `README.md`; keep workflow commands, safety boundaries, and public claims synchronized when either README changes.
- `AGENTS.md`: agent behavior and safety rules.
- `scripts/`: repository maintenance and committed release-bundle automation only; it is not either Skill's runtime package.
- `.github/workflows/`: repository CI configuration only; it is not a runtime package and requires separate explicit authorization before modification.

Do not add `README.md`, `INSTALLATION_GUIDE.md`, `QUICK_REFERENCE.md`, or `CHANGELOG.md` inside `paper_reader/` or `paper_reader_batch/`.

## 运行产物与证据边界

- Local PDF path and directory path inputs always route before Zotero text。已存在 `.pdf` -> `local_pdf`；已存在目录 -> `local_pdf_directory` 并交给 `$paper_reader_batch`；看起来像 path 但不存在 -> `unsupported_local_path`；只有其他非 path 文本才可成为 `zotero_title`。Existing local paths are not Zotero title fragments。
- Local PDF output is local-only：不搜索 Zotero、不做同名/同 DOI duplicate check、不创建 Zotero candidate/authorization、不进入 batch write lane。首次目标仍是 `<pdf_stem>_analysis/` 与 `<pdf_stem>_note.md`，重复运行只可分配 `_v2`、`_v3` 等新路径，禁止覆盖。
- Zotero title workflow 的 V2 run 默认位于安装后 skill root 的 `runs/YYYY-MM-DD/<title-slug>/`；batch run 默认位于 batch skill root 的 `runs/YYYY-MM-DD/<batch-slug>/`。两个 skill root 相互独立，batch 只能索引 `$paper_reader` 的 immutable artifacts，不能复制单篇 schema、模板、证据规则或 gate。
- V2 evidence 由 immutable `evidence/<evidence_id>/` 拥有；`context.md`、`section_context.md` 与 `figure_context.md` 必须通过 `evidence.json` membership 和 hash 解析。`section_context.md` 只用于导航，不是 canonical evidence source。Zotero `Extra` 中 eligible 的 secondary capture 只能通过 `run prepare --secondary-capture-dir` 进入同一个新的 immutable evidence membership；已发布 evidence 不得补写。
- Plan-bound Zotero run 的 source closure 必须精确为 `source/discovery.raw.json`、`source/source.json` 和 `source/secondary-plan.json`；current run、sealed evidence 和 candidate 内的 run snapshot 必须保留同一个 opaque `secondary_source_plan` ArtifactRef，且 evidence 中固定的 `secondary_plan` member 必须与 source plan 的 bytes、SHA-256 和 size 完全一致。Batch 只校验这些 identity、hash 和 closed-world membership，不解析 URL、capture state 或 finding 语义。完整且自洽的 historical V2 no-plan closure 仍可只读验证和 journal replay，但不得从 package version、wall clock、summary 或其他启发式信息猜测其版本；plan file 无 ref、ref 无 exact file/evidence copy、plan member 出现于 no-plan 或 local closure 都必须失败关闭。
- 最终 `evidence_summary` locator 必须使用 canonical 格式：`context.md page <N>`、`context.md page <N> section <Section Name>`、`context.md page <N> section <Section Name> table_candidate <N>` 或 `figure_context.md <figure_id>`。裸 `context.md` / `figure_context.md`、散文式 locator、`section_context.md` 和 secondary context 路径都必须阻断 review sealing / candidate build。
- `run init-zotero` 必须从选中 parent 的权威 raw snapshot 读取字符串 `data.extra`，在 run 分配前拒绝 selected details / parent snapshot 冲突和非字符串值，并生成绑定 item key、snapshot digest、稳定 source id 与 exact URL 的 immutable `source/secondary-plan.json`。显式 `<URL>` 定界符内逐字保留；裸 URL 大小写不敏感地识别 HTTP(S)，并去除不匹配的自然语言包装符与句末标点；非 HTTP(S) 文本不进入 plan。URL 按出现顺序去重，保留 query，排除论文 DOI / publisher URL，最多 8 个 source eligible，后续 URL 标记 `source_limit`。Rejected source 保留其顺序 id，因此调用者必须读取 plan 中实际 eligible `source_id`，不得用 `eligible_source_count` 猜连续编号。新建 current-policy plan 的 producer 必须在 run 分配前保证 canonical bytes 不超过 strict capture 同一 2 MiB 上限；内部 warnings 只接受至多 256 个字符串且每个不超过 4,096 UTF-8 bytes，不得通过隐式字符串转换或 consumer-only failure 生成不可抓取 run。这些新 admission gates 不得应用于缺少 policy 的 historical V2 plan deterministic rebuild，以保持其既有 canonical bytes 和 legacy warning projection。
- `scripts/capture-secondary-url.mjs --plan ... --source-id ... --output ...` 是唯一可进入 evidence 的 strict capture 模式；它使用 direct raw CDP，且 strict mode does not use the legacy 3456 relay，也不负责启动 Chrome。Browser endpoint 只可来自 `ZOTERO_PAPER_READER_CDP_WS_ENDPOINT`、稳定 `DevToolsActivePort` 或 loopback `/json/version`（显式 `ZOTERO_PAPER_READER_CDP_HTTP_BASE_URL`，否则只探测 9222/9229/9333）。导航前必须创建 isolated empty BrowserContext，安装 `Fetch.requestPaused` / `Network.requestWillBeSent` 拦截与 WebRTC/WebTransport/WebSocket/EventSource/worker pre-document deny，禁用 cache、绕过 service worker，并应用 `Browser.setDownloadBehavior(deny)`。所有 passive binary HTTP(S) image/media/font/prefetch 请求必须在 Fetch 阶段阻断；超长 inline `data:` 被动资源只有在 matching `Fetch.failRequest` 成功，或 matching `Network.loadingFailed` 以精确 `blockedReason="inspector"` 证明预装 `Network.setBlockedURLs` 已阻断时，才可视为已阻断，Network-only 观察或身份/类型漂移必须失败关闭。其余请求只允许无 body 的 `GET|HEAD|OPTIONS`。unsafe method/body 只有在 `Fetch.failRequest` 成功确认后才算阻断，取消失败必须 fatal。默认单 source deadline 60 秒、瞬时 request retry 最多 2 次；可用正文 200–100,000 Unicode code points，单 capture JSON 1 MiB、总正文 500,000 code points。CDP 对 decoded/encoded response 都实施单 response 8 MiB、总计 32 MiB 上限，cleartext proxy 另有单 response 8 MiB 上限。所有允许的 HTTP(S) hop 必须先解析为公网地址，再由 in-process loopback HTTP/CONNECT proxy 连接 pinned public IP；request event、guarded target session、blocked CONNECT 与 fatal proxy diagnostic 必须有硬上限，所有退出路径必须先 seal proxy。捕获 target 外的 Chrome background CONNECT 只能在没有 upstream dial 的情况下阻断并审计，owned target 观察到的未授权 authority 必须 fatal。每份 capture 必须精确绑定 `run_id`、`item_key`、`source_snapshot_sha256`、`secondary_plan_sha256`、source id 与 requested URL，并以 no-replace 发布。严格模式的 stdout 即使 argument/setup error 也必须恰好一个 machine JSON，诊断写 stderr；setup error 若未产生 artifact，调用者不得从 stdout 伪造 JSON，只能让该 source 进入 `not_attempted`/`unavailable`。Private/reserved answer、unsafe method/body、unguarded/over-limit request、authentication、popup、unsupported transport、direct-socket event、download 或 proxy violation 都使该 source `unavailable`。它不登录、不点击、不提交，并把页面文字当作不可信数据。系统 DNS 默认失败关闭；可信 TUN/fake-IP 环境只可显式使用 `--public-dns-over-https` 通过 Cloudflare 同时核验 A/AAAA，禁止整体放行合成地址段。拒绝 identity/URL/source/hash 错配、symlink、hardlink、TOCTOU 替换和额外文件；`unavailable` 只降级 secondary evidence，不阻断 PDF 主流程。Legacy positional mode 仍只是诊断材料，不得进入 review 或 candidate。
- `paper_reader.summary.v2.secondary_cross_checks` 仅用于结构化外部交叉核对；每个 eligible source 必须恰好有一个 `used|irrelevant|unavailable` assessment。Resolver 只把经验证 finding 投影到现有允许字段，不修改 Summary 或 `zotero_note.md.j2`；`30 秒结论`、一句话总结、论文背景/方法/贡献、作者明示局限与全部 canonical locator 始终 PDF-only。`evidence_summary` 始终只能引用 canonical PDF / figure evidence。
- 无 eligible `Extra` 链接时不抓网页、不生成交叉核对文字；Local PDF 和 local batch 在任何 evidence 分配前拒绝 secondary capture 路径。Batch 不抓取、解析或总结网页，只在 Zotero worker prompt 中委托 `$paper_reader` 执行该流程。

## 阅读笔记语言规则

- Zotero 阅读笔记正文默认使用中文描述；除论文题名、作者名、机构名、化学式、材料/模型/方法专名、缩写、单位、引用 locator、代码式 key 和 Zotero tags 外，不要用整句英文解释。
- 会渲染到 `note.md` / `note.html` 的自由文本字段必须优先中文化，包括 `research_object`、`main_risk_short`、`method_modules`、`workflow_steps`、`technical_details`、`key_figures.analysis`、`key_figures.why_it_matters`、缺少 `analysis` 时会作为 fallback 渲染的 `key_figures.caption`、`author_stated_limitations`、`inferred_limits` 和 `applicability_limits`。
- `note_labels` 和 Zotero metadata tags 保持英文规范 key；它们是机器标签，不是正文描述。
- V2 review validation 必须在所有 fallback 展开后的 resolved render context 上检查整段英文 prose；任何违规都是 sealing / candidate blocker，不能靠省略字段绕过。

## 环境与依赖

- Python 环境必须用 `uv` 管理。
- 默认在 `paper_reader/` 内执行命令，使用 `uv run`。
- 修改 batch runtime 时默认在 `paper_reader_batch/` 内执行命令，使用 `uv run`。
- 首次使用或 tracked-file clean install 后，先在安装后的 skill root 运行 `uv --version` 确认 `uv` 可用，再运行 `uv sync --locked` 初始化本地环境。
- 如果 `uv sync --locked` 找不到 Python `>=3.13`，在 skill root 运行 `uv python install 3.13` 后重试。
- Zotero-backed workflow 需要 Zotero Desktop 和 `zotero-mcp-plugin`：按 <https://github.com/cookjohn/zotero-mcp#readme> 下载 `.xpi`，在 Zotero 里通过 `Tools -> Add-ons` 安装，启用 `Preferences -> Zotero MCP Plugin` integrated server；默认 Streamable HTTP endpoint 是 `http://127.0.0.1:23120/mcp`。
- 缺少项目依赖时在 `paper_reader/` 内使用 `uv add` 或 `uv add --dev`，不使用 `pip install`、`conda install` 或全局安装。
- 不修改系统 Python、conda base 环境或 shell 全局配置。

## Skill 使用方式

- Use `paper_reader`: 单篇论文阅读。先执行 path-first route，再通过 V2 grouped CLI 完成 run、review、candidate 与 local/Zotero 生命周期。单篇 skill 独占 extraction、summary/review schema、render、candidate、authorization、verification 和 reconciliation 规则。
- Use `paper_reader_batch`: 多篇论文调度。Batch skill 独占 manifest、journal、lease、claim/recover/report 与 serial write lane；每篇深度阅读仍派发给 `$paper_reader`。PDF folder/path items 保持 local-output only 且不做 Zotero lookup / duplicate check。
- 本文列出的 grouped CLI 是 2.2 public runtime。`--help`、`--version` 与 schema export 必须持续匹配它；不得重新引入 V1 flat module、命令注册或兼容入口。

## Git 与发布

- 当前项目是本地 Git repo，默认分支 `main`。
- 功能开发在 feature branch 或 worktree 中进行。
- 可以创建本地 commit。
- 禁止在未获用户明确确认前执行 `git push`、创建 GitHub remote、公开发布或部署。
- 删除文件、目录或 git history 命中用户 redline，未来任何删除仍需新的明确授权。本次 2.0 迁移的 V1 source/test 删除已取得并执行独立授权。
- Historical run/output artifacts 永远视为用户数据；本次 V1 runtime 删除未触碰、移动、迁移或重新索引任何历史产物。
- `.DS_Store`、虚拟环境、缓存、本地预览文件、PDF 分析目录、生成笔记和本地 `docs/` scratch 必须被 `.gitignore` 忽略。
- `docs/` 不是发布内容；不要重新引入 tracked `docs/` 规划文档或根文档 validator，除非用户明确要求恢复公开文档树。
- 2.2 安装文档采用 clean install：只从 committed revision 导出两个独立 skill source 的 tracked files，在 `uv sync` 前以 `--release-bundle` 验证 staging tree，再移动到全新目标目录；禁止递归复制含 `.venv`、cache 或 `runs/` 的 working source，也禁止覆盖旧安装。旧安装目录可只读保留，但不得被 V2 自动发现、迁移或索引。根维护命令 `scripts/validate-committed-release-bundles.sh [git-revision] [staging-parent]` 必须解析一个精确 commit、保留仓库外 mode-0700 evidence root，并在相互独立的 install roots 中验证两个 Skill；它不得把本地通过描述为远程 CI 通过。

## Zotero 边界

- 读取 Zotero 信息优先使用 `zotero-mcp`。
- 写入 Zotero 只能通过 `zotero-mcp write_note`，且必须由用户明确触发。
- 禁止直接修改 Zotero SQLite、Zotero storage 元数据、Better Notes 配置或 Better Notes 模板。
- Zotero local API and SQLite are read-only in this project；只允许用于 live 子笔记标题/正文读取和写后验证，禁止通过 Zotero local API、SQLite 或其他非 MCP 路径写入 Zotero。
- dry-run 必须只输出预览，不写 Zotero。

## Better Notes 策略

Better Notes 是可选阅读增强层。paper_reader 生成 Zotero 子笔记，保证 Better Notes 能正常显示；不调用 `Zotero.BetterNotes.api`，不依赖 Better Notes 存在。

## 验证命令

改完 single skill 的运行时代码、测试、模板、reference、dependency 或 `SKILL.md` 后，从 `paper_reader/` 运行：

```bash
uv sync --locked
uv run pytest
uv run paper_reader --version
uv run paper_reader --help
uv run paper_reader maintenance extract-pdf tests/fixtures/minimal.pdf
uv run python scripts/validate-skill.py .
```

改完 batch runtime、测试、reference、dependency 或 `paper_reader_batch/SKILL.md` 后，从 `paper_reader_batch/` 运行：

```bash
uv sync --locked
uv run pytest
uv run paper_reader_batch --version
uv run paper_reader_batch --help
uv run python scripts/validate-skill.py .
```

只改合同文档时，至少运行受影响的 `tests/test_default_workflow_docs.py` 与两套 portable validator；若同一 task 改动运行时，再扩展到各自 full pytest、grouped help/version 与最小 PDF smoke。发布扫描必须证明 active source 不含 V1 flat runtime surface。

涉及根 README、中文 README、AGENTS 或安装说明时，必须运行与修改范围对应的 skill-root 验证命令；仓库根目录不维护单独的根文档 validator。

修改 `scripts/validate-committed-release-bundles.sh` 或其测试时，还必须从仓库根目录运行：

```bash
uv run --project paper_reader pytest scripts/tests/test_validate_committed_release_bundles.py -q
bash -n scripts/validate-committed-release-bundles.sh
```

V2 发布前必须从待发布的 committed revision 把 `paper_reader/` 和 `paper_reader_batch/` 的 tracked files 分别导出到仓库外 staging 目录；在 `uv sync` 前运行 portable validator 的 `--release-bundle` 模式，再在 staging/安装目录中运行同一组 skill-root 验证，证明两个 skill source 都自包含且未夹带运行状态。
Batch 的 local-prepare 集成测试必须通过显式 `PAPER_READER_TEST_ROOT=/path/to/separately-staged/paper_reader` 支持非 sibling staging；不得把仓库 sibling 布局当作发布合同。

## 写入规则

- 写入前必须先形成 sealed review package 和 immutable candidate，并展示固定目标、`note.md` / `note.html`、tags、hash 与所有 blockers。用户明确的真实写入意图只授权 `zotero authorize`；它不允许绕过 gate、改变 candidate 或调用第二次 MCP write。
- Local PDF 只允许 `local publish`，必须复核 source identity、candidate digest 与所有 artifact hash，并原子 no-replace 发布到 candidate 固定的 `<pdf_stem>_note[_vN].md`。它禁止任何 Zotero lookup、duplicate check、live-note refresh、authorization 或 write。
- Zotero exact search 出现多个 same normalized title 时，在 run allocation / lock / mutation 前停止并要求用户先去重；不得替用户选择 parent。
- `run init-zotero` 只消费已经保存的 raw MCP discovery bundle 与 exact expected item key；bundle 必须原样包含 exact search inventory 和 selected item details，使 duplicate normalized title 与 key selection 可离线复核。Raw 与 normalized source snapshot 都必须纳入 run identity；key mismatch 或 duplicate normalized title 都是 blocker。
- Candidate build 使用只读 live child snapshot 计算 exact versioned note title；candidate 必须包含 exact HTML、tags、parent fingerprint 和 canonical hashes。真实写入前重新 authorize，不允许直接从 candidate 推导可写 payload。
- External agent 取得未过期 authorization 后，只能调用一次 `zotero-mcp write_note(action="create", parentKey=<authorization parentKey>, content=<exact authorization HTML>, tags=<authorization tags>)`。Content 必须是 authorization 绑定的 HTML，禁止 Markdown、override 或重新渲染。
- 写调用后必须立即 read-only verify；若返回丢失、进程 crash、authorization/write lease 过期或结果不确定，进入 reconciliation/uncertain，不得自动重发。三元组唯一匹配只定位候选 note；只有对其 exact parent、note key、exact title、complete tags、required headings、minimum length 和 canonical HTML hash 全部验证通过才能确认 written。
- Batch 的 manifest 默认 policy 仍可表达 `zotero_write`；显式 dry-run 使用 `prepare_only`。Batch CLI 永远不调用 Zotero MCP `write_note`，只管理 journal、lease、authorization handoff、result 与 report。PDF batch items 始终 `effective_write_policy=local_only`。
- Single-paper write 永远 create 新的 versioned Zotero child note，不 update 既有 `[Codex Summary]` note。Authorization title availability 与 parent fingerprint 必须在每次授权时重新只读检查。
