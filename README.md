# PFN — 临床试验项目导航工具

基于 PyQt6 的桌面应用，用于在 **Z 盘网络路径** 下管理临床试验项目、快速浏览文件结构，并与 **SAS Enterprise Guide**、**VS Code** 等工具联动打开代码与文档。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **项目管理栏** | 左侧树：按 projects / unblinded / users 分类；支持「产品 → 试验 → 子目录」层级、搜索定位、添加/删除、打开所在文件夹；标题区可切回待办/分析。 |
| **右侧视图** | 无左侧选中：显示「我的待办 / 项目数据分析」；有选中且可解析为收藏目录：显示文件树。见下文「归类规则」。 |
| **右侧文件树** | 对**收藏项**（`config` 中有对应记录）展示按项目类型归类的聚合目录；支持双击/右键打开、显示修改时间；**.doc/.docx/.rtf** 可多选后右键「转换为 PDF」（同目录生成独立 PDF，需本机安装 Microsoft Word）；**可将选中文件或文件夹拖出窗口**，拖到桌面或资源管理器等位置，由系统完成复制/移动。 |
| **添加项目** | 对话框支持三目录（projects / unblinded / users）按**产品**搜索与快速定位；**搜索结果优先展示「文件夹名以关键词结尾」等更相关项**，下拉列表与树定位时**将匹配项滚到可视区域顶部**；可多选目录并自动解析为产品/试验加入收藏；支持覆盖/跳过已存在路径。 |
| **SAS EG 集成** | .sas 与 SAS 数据集（.sas7bdat/.sas7bndx/.sas7bcat/.sd2）差异化打开：`.sas` 走 EG 自动化展开；数据集直接调用 `SEGuide.exe` 传参打开。 |
| **代码/文档打开** | `.sas` 保留 SAS EG / VS Code；SAS 数据集仅 SAS EG；PDF 可选默认查看器。 |
| **Utility 公共目录** | 左侧固定入口，点击后在右侧展示 `Z:\projects\utility` 目录树。 |
| **工作台（工具入口）** | 项目管理页内置工作台卡片（如 PDTManager/QCT_Tools/RTFtoPDF），启动时按规则扫描固定目录并选择最新 exe。 |
| **配置与规则** | 配置文件 `config.json`（自动创建、带回退优先级）；内置匹配规则（aCRF、protocol、SAP、shell、顶线、setup 等）可扩展。 |
| **单文件分发** | Windows 打包产物为单文件 `PFN.exe`（PyInstaller onefile），可复制到任意路径运行；任务栏图标优先读取同目录 `icon.ico`，无则回退内嵌/PE 图标。 |

---

## 核心功能说明

### 1. 项目管理栏（左侧）

- **分类**：根节点为 `projects`、`unblinded`、`users`（有对应收藏时才显示 users）。
- **层级**：
  - **projects / unblinded**：产品 → 试验 → 子目录（叶子为具体收藏路径）。
  - **users**：先按 `unblinded` / `projects` 分，再按产品 → 试验 → 子目录；仅两层路径时从试验名解析产品前缀（如 `HRS7450_201` → 产品 `HRS7450`），实现与 projects 一致的归类。
- **操作**：点击「+ 添加项目」从 Z 盘树多选并自动归类；右键节点可「打开所在文件夹」或「删除」产品/试验/子项目；同路径在树中按 `full_path` 去重，避免重复节点。
- **与右侧联动**：点击左侧标题「项目管理栏」区域可取消树选中，右侧回到「我的待办 / 项目数据分析」；选中某条**可浏览**的节点时，右侧切换到文件树视图。

### 2. 右侧视图与归类规则（重要）

- **两视图切换**：
  - **无选中**：右侧默认显示 **「我的待办」** 与 **「项目数据分析」** 两个标签页（项目管理、任务与图表）。
  - **有选中**：右侧切换到 **文件树**，展示当前节点对应目录下的内容（见下）。
- **收藏项 vs 普通目录**（决定右侧是「归类树」还是「扁平资源管理器」）：
  - 若选中节点对应 **`config.json` 里的一条收藏**（叶子 / 试验 / 父分组 / 置顶解析出的收藏），且路径有效，则使用**内置归类布局**（与早期版本一致）。
  - 若仅选中**没有对应收藏记录的**物理目录（例如仅展开到产品根、`Z:\projects` 等），则使用**扁平目录树**（懒加载展开，类似资源管理器）。
- **projects / unblinded**：归类树包含 **data、M5、program、reports、protocol、data_management、statistics、review_comments、logs、util、Documents** 等聚合节点；`program` 下为 `06_programs` / `09_validation`（界面显示为 programs / validation）；`util` 下为 `utility/macros`、`utility/metadata`、`utility/tools`（显示为 macros / metadata / tools）。
- **users**：归类树**仅**包含 **program** 与 **util** 两棵聚合（同样基于上述相对路径），**不**包含 M5、Documents 等整块，结构更精简。
- **program 与 Documents**：规则见下节；与 `dir_type` 为 `projects` / `unblinded` / `users` 时的展示策略一致。

### 3. 右侧文件树（数据来源与细节）

- **数据来源**：对**收藏项**选中后，根据项目路径与 `config` 中的 **match_rules**、**fixed_paths** 聚合展示。
- **projects / unblinded**：展示 M5、program、protocol、data_management、statistics、review_comments、util 等聚合节点；每个节点对应项目下的相对路径（如 `06_programs`、`utility/documentation/01_protocol`）；部分节点下为规则匹配到的文档（如 aCRF、protocol、SAP、shell、顶线、setup、SDTM_PDS 等）。
- **users**：展示 program、util 等聚合节点（无 M5），结构更精简。
- **固定路径**：如 `07_logs`、各 documentation 子路径等，可在配置中调整；`07_logs` 下可展开显示 .xml 文件及修改时间。
- **program 聚合过滤**：`program`（`06_programs` / `09_validation`）目录树内仅展示 `.sas` 程序文件，隐藏 `.lst`、`.txt` 等非 SAS 文件。
- **Documents 展示策略**：初次展开仅显示“常用 xlsx”；对 `Documents` 节点执行刷新后，切换为展示该目录下“全部 xlsx”。
- **列**：第一列为名称，第二列为修改时间（右对齐、灰色）。
- **拖放到系统文件夹**：在右侧文件树中可多选本地存在的文件或文件夹，按住左键拖出应用窗口，可放到桌面、资源管理器其它目录或支持文件拖放的应用中；松手后的复制/移动与系统资源管理器行为一致（单文件拖拽时沿用界面同款文件图标作为拖拽缩略图）。

### 4. 添加项目

- 对话框从 **Z 盘根** 懒加载：先显示 projects / unblinded / users，展开后加载子目录。
- **users** 下展开到 userid 后显示 `projects`、`unblinded`，再进入具体路径。
- **产品搜索**：
  - 输入关键词后，下拉结果在「命中强弱、来源（projects / unblinded / users）」排序基础上，**优先将「规范化后的产品文件夹名以关键词结尾」的项排在前面**（例如搜 `5965` 时更易将 `HRS5965` 排在列表前部），再辅以完全匹配、名称长度与字母序。
  - 每次刷新下拉列表后会**滚回列表顶部**，保证当前最优匹配（第 1 条）出现在可视区域最上方。
  - 从下拉选择或回车确认跳转后，右侧树会**将目标节点滚到可视区域顶部**（`PositionAtTop`），避免仅「保证可见」而把高亮项挤在视口最下方。
- 多选目录后，按路径解析为「产品 → 试验 → 子目录」并写入收藏；可选覆盖已存在路径。
- 支持 Z 盘路径如 `Z:\projects\...`、`Z:\users\userid\unblinded\...` 等。

### 5. SAS EG 打开（代码/数据集差异化）

- **`.sas` 代码文件**：
  - 右键支持 `SAS EG` 与 `VS Code`；
  - 选择 `SAS EG` 时执行自动化：新开 EG → 展开「服务器 → SASApp → 文件」→ 定位路径并打开；
  - 适用于 projects / users 路径，仍保留原自动化兜底逻辑。
- **SAS 数据集文件**（`.sas7bdat/.sas7bndx/.sas7bcat/.sd2`）：
  - 右键仅保留 `用 SAS EG 打开`（无 VS Code）；
  - 不做 UI 自动化、不展开服务器树；
  - 直接调用 `_find_sas_eg()` 定位 `SEGuide.exe`，再 `subprocess.Popen([seguide_path] + data_paths)` 一次性传入多文件。
- **多选行为**：多选数据集时单次调用 EG 并传入全部路径，目标效果与资源管理器右键“使用 SAS Enterprise Guide 打开”一致，尽量在同一 EG 窗口加载。

### 6. 其他文件打开

- **PDF**：双击可弹窗选择打开方式（如系统默认、Adobe 等）。
- **Excel / 其他**：通过系统关联或 ShellExecute 打开。
- **打开所在文件夹**：收藏/文件节点右键「打开所在文件夹」；优先复用已打开的资源管理器窗口并定位到路径或选中文件。

#### setup.xlsx（编辑版 / 参考版双开）

用于在同一项目下**先编辑、再对照**两份 Setup，且避免 Excel 对**同一原文件路径**重复打开时出现「同名无法打开」等问题。

| 操作 | 行为 |
|------|------|
| **第一次打开**（当前 Excel 里**还没有**任何名为 `setup.xlsx` 的工作簿） | 直接打开**网络盘上的原文件**（可编辑）。 |
| **第二次打开**（Excel 里**已经有一份** `setup.xlsx` 打开——**包括先开了项目 A 的 setup，再点项目 B 的 setup**，文件名相同即算） | **不再**从网络路径直接再打开 `setup.xlsx`（否则会触发 Excel「无法同时打开两个同名工作簿」）；将**当前点击**的那份原文件复制到本机临时目录 **`%TEMP%\PFN_Reference\`**，文件名为 **`{项目名称}_Setup_参考版.xlsx`**（项目名称优先取项目管理配置中的子项目名称 `subproject_name`，否则使用路径解析出的试验目录名如 `SHRxxxx_xxx`），**覆盖**同名旧文件后，用 Excel 打开该临时副本。 |

**实现要点（与代码一致）**

- 每次点击都重新判断：通过 **pywin32 / win32com** 连接已运行的 Excel，检查是否已有任意 **`setup.xlsx` 工作簿**（按文件名，不限是否同一路径）；未安装或 COM 失败时，用「**当前点击路径**文件独占读是否失败」作为弱兜底（无法可靠处理「已开 A 再开 B」的跨目录同名，**强烈建议安装 pywin32**）。
- **不**使用「第几次点击」的进程内缓存；关闭 Excel 或重启工具后，行为仍由「原文件当前是否已在 Excel 中打开」决定。
- 参考版与项目数据**不同目录**，仅临时文件；建议在环境中安装 **pywin32** 以获得稳定的「是否已打开」判断。

### 7. 配置

- **统一位置（开发与打包一致）**：`config.json` 固定为 **`%USERPROFILE%\PFN_Config\config.json`**（在默认用户目录布局下即 **`C:\Users\<当前 Windows 登录名>\PFN_Config\config.json`**）。收藏、待办、`project_management`、个人待办附件元数据等均读写此文件；个人待办附件文件在同目录下的 **`PFN_Data\personal_task_attachments\`**。
- **版本升级**：更换或移动 `PFN.exe` 不影响上述路径中的数据；只要在同一 Windows 用户下运行，即沿用同一配置。
- **从旧版迁移**：若你曾在 **exe 旁** 或 **项目目录** 使用过另一份 `config.json`，请将该文件（及同目录 **`PFN_Data`** 文件夹，若有）**复制到** `%USERPROFILE%\PFN_Config\`，覆盖或合并后再启动新版本。
- **内容**：`favorite_projects`（收藏列表）、`match_rules`（文档匹配规则）、`fixed_paths`（右侧固定展示路径）、`sas_open`（.sas 默认打开方式及编码）、`personal_tasks`、`project_management` 等。

---

## 运行与打包

### 环境要求

- **Python 3**（建议 3.10+）
- **PyQt6**
- 可选：**pywin32**（解析 .lnk、SAS EG 路径等）、**pywinauto**（SAS EG 自动化，否则仅传参启动）

### 安装依赖

```bash
pip install PyQt6
# 可选，推荐
pip install pywin32 pywinauto
```

### 运行

```bash
python app_qt.py
```

### 打包为单文件 exe（Windows）

在项目根目录执行 **`build.bat`**（或 `pyinstaller build.spec`），生成 **`PFN_app\PFN.exe`**：无控制台、单文件可任意路径运行。建议将同目录下的 **`icon.ico`** 一并分发给对方（脚本会自动复制到 `PFN_app\`）。

### config.json 位置（固定用户目录）

程序**始终**使用当前 Windows 用户下的：

`%USERPROFILE%\PFN_Config\config.json`

（一般为 `C:\Users\<你的登录名>\PFN_Config\config.json`）。首次运行若不存在会自动创建。打包升级 exe **不会**改变该路径，数据与 exe 所在位置无关。

- **分发预置配置**：若需给他人一份已有收藏/待办，请将准备好的 **`config.json`**（及同目录 **`PFN_Data`**，若有附件）放入对方机器的 **`%USERPROFILE%\PFN_Config\`**，再启动程序。
- **`%APPDATA%\PFN\pfn_config_dir.txt`**：打包后仍可能写入，仅作记录 PFN_Config 目录之用；**不再**作为切换配置路径的依据。

---

## 项目结构（简要）

| 文件 | 说明 |
|------|------|
| `main.py` | 程序入口：AppUserModelID、单实例锁（`pfn_app.lock`）、应用/窗口图标与 Win32 `WM_SETICON` 补强。 |
| `PFN_silent.pyw` | Windows 静默入口（pythonw/.pyw），避免控制台窗口闪烁。 |
| `app_qt.py` | 主界面与业务逻辑：收藏树、右侧文件树、添加项目对话框与搜索、SAS EG 自动化、右键菜单等。 |
| `config_manager.py` | 配置读写：收藏、匹配规则、固定路径、SAS 打开方式；**`config.json` 固定为 `%USERPROFILE%\PFN_Config\config.json`**。 |
| `zdrive_scanner.py` | Z 盘懒加载扫描：projects/unblinded/users，users 下 userid → projects/unblinded 的 source_id 计算。 |
| `file_matcher.py` | 按 match_rules 匹配项目文档（aCRF、protocol、SAP、shell、顶线、setup 等）。 |
| `workbench_launcher.py` | 工作台工具启动辅助：缓存/扫描 exe、Windows 静默启动参数等。 |
| `icons_pfn.py` | UI 图标绘制/加载（文件夹、勾选等）。 |
| `build.bat` | Windows 一键构建脚本（ASCII-only），输出 `PFN_app\PFN.exe`。 |
| `build.spec` | PyInstaller **单文件（onefile）** spec：生成 `PFN.exe`（无控制台），包含 `assets/app_icon.ico`。 |
| `assets/` | `app_icon.ico`、分发说明 `DISTRIBUTION_zh.txt`、logo 源图等。 |
| `scripts/build_app_icon_from_png.py` | 从 PNG 生成 ICO（用于构建时同步 `icon.ico`）。 |
| `tests/test_workbench_launcher.py` | 工作台启动辅助的单元测试。 |
| `.cursor/rules/` | Cursor 规则：项目约定、工作台约定、UI 负载安全等。 |
| `SAS_EG_集成与调试说明.md` | SAS EG 集成与调试说明（路径转换、树展开、常见问题）。 |

---

## 使用提示

1. **Z 盘**：需已映射并可访问；左侧「添加项目」与右侧文件树均依赖 Z 盘路径。
2. **SAS EG**：自动化需安装 pywinauto；若未安装，双击 .sas 仍可选 SAS EG，但会以降级方式传参启动（可能乱码）。
3. **默认打开方式**：`.sas` 文件可在右键菜单设置默认打开方式（SAS EG / VS Code）；数据集文件不提供 VS Code。
4. **多选打开**：Ctrl 多选多个 `.sas`/数据集后右键 `用 SAS EG 打开`；其中数据集会一次性传参提交到 EG。
5. **收藏去重**：同一路径在收藏树中只显示一次；若配置中误重复，界面展示时会按 `full_path` 去重。
6. **拖出文件**：在「项目管理」右侧文件树中选中文件或文件夹后，可拖出窗口到桌面或资源管理器完成复制/移动（多选时一并拖出）。
7. **添加项目搜索**：产品搜索下拉会优先展示「文件夹名以关键词结尾」等更相关结果，并自动滚到列表顶部；回车或点选跳转后，树会将目标节点滚到可视区域顶部。

---

## 更新日志

### 2026-05

- **配置路径**：`config.json` 固定为 `%USERPROFILE%\PFN_Config\config.json`（按当前 Windows 用户），不再从 exe 旁或「上次目录」切换，避免升级/拷贝 exe 后误用空配置。旧数据在其它位置的需手动复制到 PFN_Config。
- **右侧文件树 — 系统拖放**：支持将选中项拖出应用窗口至桌面、资源管理器或其它接受文件 URL 的目标；使用系统标准拖放语义（复制/移动由目标位置决定）。详见上文「### 3. 右侧文件树」中的「拖放到系统文件夹」。
- **添加项目 — 搜索与定位**：产品搜索在排序上强化「文件夹名以关键词结尾」等优先级；刷新下拉后列表滚回顶部；从搜索跳转到树节点时使用 `PositionAtTop`，避免匹配项出现在视口最下方。详见上文「### 4. 添加项目」中的「产品搜索」。

---

## 许可证与维护

本项目为内部临床试验项目导航与 SAS 集成工具。功能迭代与问题排查可参考代码注释及 `SAS_EG_集成与调试说明.md`。
