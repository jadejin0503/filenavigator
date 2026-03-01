# PFN — 临床试验项目导航工具

基于 PyQt6 的桌面应用，用于在 **Z 盘网络路径** 下管理临床试验项目、快速浏览文件结构，并与 **SAS Enterprise Guide**、**VS Code** 等工具联动打开代码与文档。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **收藏项目库** | 左侧树：按 projects / unblinded / users 分类，支持「产品 → 试验 → 子目录」层级；支持添加、删除、打开所在文件夹。 |
| **右侧文件树** | 选中收藏后展示项目下的聚合目录（program、util、M5、protocol 等）及匹配文档；支持双击/右键打开、显示修改时间。 |
| **添加项目** | 从 Z 盘树中多选子目录，自动解析为产品/试验并加入收藏；支持覆盖/跳过已存在路径。 |
| **SAS EG 集成** | .sas / .sas7bdat 可用 SAS EG 打开：新开 EG 窗口 → 自动展开服务器树到目标路径 → 双击打开（支持单文件与 Ctrl 多选批量）。 |
| **代码/文档打开** | .sas 可选 SAS EG 或 VS Code；.sas7bdat 用 SAS EG；PDF 可选默认查看器；支持右键设置默认打开方式。 |
| **Utility 公共目录** | 左侧固定入口，点击后在右侧展示 `Z:\projects\utility` 目录树。 |
| **配置与规则** | 配置文件 `config.json`；内置匹配规则（aCRF、protocol、SAP、shell、顶线、setup 等）可扩展。 |

---

## 核心功能说明

### 1. 收藏项目库（左侧）

- **分类**：根节点为 `projects`、`unblinded`、`users`（有对应收藏时才显示 users）。
- **层级**：
  - **projects / unblinded**：产品 → 试验 → 子目录（叶子为具体收藏路径）。
  - **users**：先按 `unblinded` / `projects` 分，再按产品 → 试验 → 子目录；仅两层路径时从试验名解析产品前缀（如 `HRS7450_201` → 产品 `HRS7450`），实现与 projects 一致的归类。
- **操作**：点击「+ 添加项目」从 Z 盘树多选并自动归类；右键节点可「打开所在文件夹」或「删除」产品/试验/子项目；同路径在树中按 `full_path` 去重，避免重复节点。

### 2. 右侧文件树

- **数据来源**：选中左侧收藏后，根据项目路径与 `config` 中的 **match_rules**、**fixed_paths** 聚合展示。
- **projects / unblinded**：展示 M5、program、protocol、data_management、statistics、review_comments、util 等聚合节点；每个节点对应项目下的相对路径（如 `06_programs`、`utility/documentation/01_protocol`）；部分节点下为规则匹配到的文档（如 aCRF、protocol、SAP、shell、顶线、setup、SDTM_PDS 等）。
- **users**：展示 program、util 等聚合节点（无 M5），结构更精简。
- **固定路径**：如 `07_logs`、各 documentation 子路径等，可在配置中调整；`07_logs` 下可展开显示 .xml 文件及修改时间。
- **列**：第一列为名称，第二列为修改时间（右对齐、灰色）。

### 3. 添加项目

- 对话框从 **Z 盘根** 懒加载：先显示 projects / unblinded / users，展开后加载子目录。
- **users** 下展开到 userid 后显示 `projects`、`unblinded`，再进入具体路径。
- 多选目录后，按路径解析为「产品 → 试验 → 子目录」并写入收藏；可选覆盖已存在路径。
- 支持 Z 盘路径如 `Z:\projects\...`、`Z:\users\userid\unblinded\...` 等。

### 4. SAS EG 打开 .sas / .sas7bdat

- **入口**：双击 .sas 会弹出「选择打开方式」（SAS EG / VS Code），可勾选「下次默认使用」；右键可设默认打开方式；.sas7bdat 默认用 SAS EG。
- **流程**：每次**新开一个 SAS EG 进程** → 等待主窗口与服务器树就绪 → 在主窗口左侧树中展开「服务器 → SASApp → 文件」→ 按路径类型展开 **projects** 或 **users → project/unblinded** → 再展开到目标文件夹 → 在树中双击目标文件（或 Ctrl 多选后依次双击）。
- **路径转换**：Z 盘路径会转换为 SAS 服务器 DDT 路径（如 `Z:\...` → `/u01/app/sas/sas9.4/DocumentRepository/DDT/...`），兼容 projects / users 的 project 与 unblinded。
- **等待策略**：启动后按「服务器树是否就绪」精准等待，减少固定长时间等待；展开「文件」节点时略增等待以适配 SAS 加载。
- **失败时**：自动化失败会降级为传参启动 SEGuide（可能乱码），并提示可手动打开文件夹后双击文件。

### 5. 其他文件打开

- **PDF**：双击可弹窗选择打开方式（如系统默认、Adobe 等）。
- **Excel / 其他**：通过系统关联或 ShellExecute 打开。
- **打开所在文件夹**：收藏/文件节点右键「打开所在文件夹」；优先复用已打开的资源管理器窗口并定位到路径或选中文件。

### 6. 配置

- **开发环境**：`config.json` 位于项目目录。
- **打包后**：`config.json` 位于 `%APPDATA%\PFN\`，便于分发给他人时不含开发者个人收藏。
- **内容**：`favorite_projects`（收藏列表）、`match_rules`（文档匹配规则）、`fixed_paths`（右侧固定展示路径）、`sas_open`（.sas 默认打开方式及编码）等。

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

```bash
pyinstaller build.spec
```

生成无控制台窗口的 `dist/PFN.exe`。

### config.json 查找优先级（适配「仅复制 exe 到桌面」）

程序按以下顺序找配置，**仅复制 exe 到桌面也能自动找到原来的收藏**（只要曾在「有 config 的目录」运行过一次）：

| 优先级 | 位置 | 说明 |
|--------|------|------|
| 1 | **程序运行目录**（exe 所在目录）的 `config.json` | 与原有逻辑一致；若把 exe 和 config 放同一文件夹，优先用这份。 |
| 2 | **上次使用过的 config 所在目录** | 程序会记住「上次读到的 config 在哪个目录」（记在 `%APPDATA%\PFN\pfn_config_dir.txt`）。把 exe 单独复制到桌面后，若运行目录没有 config，会自动去该目录找（通常是 dist 或项目目录），收藏不丢失。 |
| 3 | **C:\Users\\<当前用户名>\PFN_Config\config.json** | 若 1、2 都没有，则在此创建空配置；新用户添加的项目会保存在这里。 |

- **本机：复制 exe 到桌面** → 先在 **dist**（或带 config 的目录）运行一次 PFN.exe，再只把 **PFN.exe** 拷到桌面；之后点桌面的 exe，会自动用 dist 里的 config，项目不会丢。若希望桌面单独一份配置，可在桌面建文件夹并放入 **PFN.exe + config.json**，则优先用桌面这份。
- **发给别人** → 只发 **PFN.exe** 一个文件；对方电脑没有「上次使用目录」记录，会走优先级 3，在对方 `C:\Users\<对方用户名>\PFN_Config\` 下生成空配置，**不会看到你的项目**。

---

## 项目结构（简要）

| 文件 | 说明 |
|------|------|
| `app_qt.py` | 主界面与业务逻辑：收藏树、右侧文件树、添加项目、SAS EG 自动化、打开方式选择与右键菜单等。 |
| `config_manager.py` | 配置读写：收藏、匹配规则、固定路径、SAS 打开方式；开发/打包不同 config 路径。 |
| `zdrive_scanner.py` | Z 盘扫描：根目录 projects/unblinded/users，users 下 userid → projects/unblinded 的懒加载与 source_id。 |
| `file_matcher.py` | 按 match_rules 在项目路径下匹配文档（aCRF、protocol、SAP、shell、顶线、setup 等）。 |
| `icons_pfn.py` | 图标资源。 |
| `build.spec` | PyInstaller 配置，单 exe、无控制台、不打包 config。 |
| `SAS_EG_集成与调试说明.md` | SAS EG 集成与调试说明（路径转换、树展开、常见问题）。 |

---

## 使用提示

1. **Z 盘**：需已映射并可访问；左侧「添加项目」与右侧文件树均依赖 Z 盘路径。
2. **SAS EG**：自动化需安装 pywinauto；若未安装，双击 .sas 仍可选 SAS EG，但会以降级方式传参启动（可能乱码）。
3. **默认打开方式**：.sas 文件右键 →「设置默认打开方式」→ SAS EG 或 VS Code，之后双击即按默认打开。
4. **多选打开**：在右侧文件树中 Ctrl+点击多个 .sas/.sas7bdat（同文件夹），再双击或右键「用 SAS EG 打开」，会在同一新 EG 窗口中依次打开。
5. **收藏去重**：同一路径在收藏树中只显示一次；若配置中误重复，界面展示时会按 `full_path` 去重。

---

## 许可证与维护

本项目为内部临床试验项目导航与 SAS 集成工具。功能迭代与问题排查可参考代码注释及 `SAS_EG_集成与调试说明.md`。
