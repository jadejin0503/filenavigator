# SAS EG 工具功能优化 — 集成与调试说明

## 一、本次修改位置概览

### 1. 下拉框分类逻辑（user 与 M5）

| 位置 | 说明 |
|------|------|
| `_source_root_name(dir_type)` | 增加对 `users` 的识别，返回 `"users"`。 |
| `_path_segments_after_root(path, dir_type)` | 当 `dir_type` 为 `users-xxx-projects` 形式时，跳过前 3 段（users、userid、projects），返回「产品→试验→子目录」段。 |
| `_load_favorites()` | 对 `dir_type.startswith("users")` 的收藏按产品/试验做 `by_pt` 聚合，与 projects 一致；并修正 product_root_path 的 break 缩进。 |
| `_do_refresh_tree()` 中 `path_order` | **users**：去掉 `("M5", [...])`；**projects/unblinded**：同样去掉 M5，右侧不再显示 M5 分类。 |
| `_project_from_path()` | 对 `dir_type.startswith("users")` 使用 `_product_trial_from_path` 解析 display_name；并修正 return 缩进。 |

### 2. 单文件打开修复（树导航 + 文件列表选中）

| 位置 | 说明 |
|------|------|
| `_open_sas_eg_automation()` | Ctrl+O 后先 `_saseg_click_server_tab(app)` 切换到「服务器」标签，等待 4s；复用现有树导航（服务器→SASApp→文件→folder_parts）到目标文件夹；导航后 `current.click_input()` + 等待 4s 刷新右侧列表；单文件时调用 `_select_file_in_list(app, file_names[0], send_keys)` 在列表中选中目标文件并点击「打开」。 |
| `_saseg_click_server_tab(app)` | **新增**。在打开对话框中查找并点击「服务器」/「Servers」标签（TabItem 或标题匹配控件），确保左侧树与右侧文件列表可见。 |
| `_select_file_in_list(app, file_name, send_keys)` | **新增**。在右侧文件列表中按文件名（忽略大小写）定位 ListItem/DataItem，`set_focus` → `ensure_visible` → `click_input`，等待 4s 后 `_click_open_button_then_enter`。先尝试 ListView/List/DataGrid 内子项，再兜底遍历对话框下所有 ListItem/DataItem。未找到则弹窗「文件列表中未找到目标文件，请检查路径或文件名」并提示使用 inspect 查看控件类型。 |

---

## 二、集成说明（替换/新增位置）

- **替换**：`_source_root_name`、`_path_segments_after_root`、`_convert_path_for_saseg`、`_load_favorites` 中 users 的 by_pt 分支与 product_root_path 的 break、`_do_refresh_tree` 的 path_order 与 for 循环结构、`_open_sas_eg_automation` 中单文件分支与等待时间、`_project_from_path` 的 display 与 return。
- **新增**：`_saseg_click_server_tab`（在 `_find_file_node` 之后）、`_select_file_in_list`（在 `_batch_select_and_open_in_dialog` 之前）。
- **其他**：已顺带修正多处既有缩进/语法错误（如 `_on_fav_selected`、`_project_from_path`、`open_file` 内 try/except、`_find_vscode` 的 return）。

---

## 三、调试指南（常见问题）

### 1. 路径转换错误

- **现象**：弹窗「路径转换错误」或单文件未在 EG 中打开。
- **排查**：
  - 在控制台查看是否有 `[SAS EG] 路径转换: '...' -> '...'` 的打印；确认输入为 Z 盘绝对路径，输出为 `/u01/app/sas/sas9.4/DocumentRepository/DDT/...`。
  - 若输出为空或异常，检查 `_convert_path_for_saseg` 是否被正确调用（单文件分支是否走到）。
- **处理**：确认文件路径为 `Z:\` 开头且存在；非 Z 盘路径会只做 `\` → `/`，不改为 DDT。

### 2. 文件不存在

- **现象**：提示「文件不存在: xxx」。
- **排查**：在调用 `_open_with_saseg` 前，工具会检查 `os.path.exists(p)`；若 Z 盘未映射或路径错误会报此错。
- **处理**：确认 Z 盘已连接、路径可访问；若为网络盘，先在本机资源管理器中打开该路径验证。

### 3. 窗口激活失败 / 树或列表未响应

- **现象**：打开对话框弹出后未切换到「服务器」标签，或树展开后右侧列表无反应。
- **排查**：每步前均对 `app.Dialog` 执行 `set_focus()`；切换标签与展开节点后已增加 4–5 秒等待。
- **处理**：若 EG 响应更慢，可适当增大 `_open_sas_eg_automation` 与 `_select_file_in_list` 中的 `time.sleep`。

### 4. 文件列表中未找到目标文件

- **现象**：弹窗「文件列表中未找到目标文件，请检查路径或文件名」。
- **排查**：单文件流程为「切换到服务器标签 → 树展开到目标文件夹 → 在右侧文件列表中按文件名选中 → 点击打开」。若列表未刷新或控件类型与代码不一致，会找不到项。
- **处理**：使用 **inspect.exe / Accessibility Insights** 确认文件列表的 ControlType（见下方「使用 inspect 确认文件列表控件」）。

### 5. 使用 pywinauto / inspect 确认文件列表控件

- **目的**：确认 SAS EG「打开」对话框右侧文件列表的 **ControlType**（如 ListView、List、DataItem、ListItem），以便在 `_select_file_in_list` 中准确定位。
- **步骤**：
  1. 安装 pywinauto 后，在 Python 的 `site-packages` 或 pywinauto 安装目录下查找 **inspect.exe**（或使用 Windows SDK 的 **inspect.exe**、**Accessibility Insights for Windows**）。
  2. 启动 SAS EG，手动打开「文件→打开」对话框，切换到「服务器」标签并展开到目标文件夹，使右侧显示文件列表。
  3. 运行 inspect.exe，用鼠标拖拽「十字准星」到右侧文件列表区域（或到某个文件名上）。
  4. 在 inspect 中查看该控件的 **ControlType**（如 `List`、`ListView`）、**ClassName**，以及其子项的 **ControlType**（如 `ListItem`、`DataItem`）。
  5. 若 `_select_file_in_list` 中使用的类型与 inspect 显示不一致，可在该方法中增加对应 ControlType 的查找（如 `Pane`、`Table` 等），或增加对 `children()` 的遍历以适配实际结构。

### 6. 多文件打开（多选）逻辑

- **说明**：多选仍走「切换服务器标签 → 树导航到共同父文件夹 → 列表中批量选中（Ctrl+点击）→ 点击打开」；单文件走「树导航到父文件夹 → _select_file_in_list 选中一个文件 → 点击打开」。
- **排查**：多选时若失败，检查 `_common_folder_and_files` 是否报「不在同一文件夹」；以及 `_batch_select_and_open_in_dialog` 是否找到对应 ListItem/DataItem。

### 7. 依赖

- **pywinauto**：自动化必需，缺失会降级为传参打开（可能乱码）。安装：`pip install pywinauto`。
- **SAS EG 路径**：固定为 `C:\Program Files\SaS\SASHome\SASEnterpriseGuide\8\SEGuide.exe`，若安装在其他路径需改 `_open_with_saseg` 中的 `seguide_path`。

---

## 四、验收要点

- **下拉框**：左侧可见「users」→「产品名」→「子文件夹」层级；选中 user 下子文件夹后，右侧展示对应文件且**无 M5**。
- **路径拼接**：选中 user / 产品 A / test 时，`current_fav["full_path"]` 为 `Z:\users\...\产品A\test` 形式（与 projects 一致）。
- **单文件打开**：选中一个 Z 盘 .sas 文件，右键「用 SAS EG 打开」→ EG 启动 → 打开对话框 → **自动切换到「服务器」标签** → 左侧树自动展开到目标文件夹 → **右侧文件列表中自动选中目标文件** → 自动点击「打开」→ 该文件在 EG 中打开；控制台有「已切换到服务器标签」「已在文件列表中选中目标文件」等日志；失败时弹窗提示并降级传参打开。
