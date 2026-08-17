# nvsipl_camera 并行交互执行模式 - 调试记录与变更日志

## 文档信息

| 项目 | 内容 |
|---|---|
| 涉及用例 | FT_002_01 等阻塞型 nvsipl_camera 功能测试 |
| 目标设备 | QNX 8.0 (root@10.127.1.100) |
| 工作目录 | `/storage/zja/` |
| 起始日期 | 2026-08-13 |
| 最后更新 | 2026-08-14 |
| 状态 | 基本功能验证通过，持续优化中 |

---

## 1. 需求背景

### 1.1 用例场景

FT_002_01 类功能测试的典型步骤：

```
1、输入命令：./nvsipl_camera -c MIXGROUP_PREDEV_30FPS_MAX96724_CPHY_x4 -m "0 0 0x0100 0" -R -1 -2 -s -0 -Z
2、输入 gc 10
3、起流后，在起流终端输入'al'指令检查是否成功读到相机有效像素信息
```

**关键点**：
- nvsipl_camera 是**阻塞型**进程（无 `-r N` 参数，不会自动退出）
- 需要在 nvsipl 运行期间通过 stdin 注入交互命令（gc、al、ro 等）
- 需要捕获交互命令的输出来判断用例 pass/fail
- 执行完毕后需要发送 `q` 退出 nvsipl，不能阻塞后续用例

### 1.2 nvsipl_camera 交互命令

| 命令 | 说明 | 输出特征 |
|---|---|---|
| `gc <ID>` | 获取 Sensor 自定义接口，触发出帧 | `sensor_id :N` + 菜单 + fps |
| `al` | 读取 action line（有效像素信息） | `Sensor ID N belongs to...`, `Vertical:`, `horizontal:` |
| `ro` | 读取 readout time | `readout` 相关数据 |
| `dl <ID>` | 禁用链路 | `Disable Link: N` |
| `elr <ID>` | 使能链路（带模块复位） | `Enable Link: N` |
| `el <ID>` | 使能链路（不带复位） | 同上 |
| `ed` | 读取 eeprom 数据 | eeprom 相关 |
| `th` | 温度直方图 | temperature 相关 |
| `df` | 检测模块故障 | fault 相关 |
| `q` | 退出 nvsipl_camera | 进程结束 |

### 1.3 判定逻辑

- `al` 命令：输出中应包含 `Vertical`、`horizontal` 等像素信息 → Pass
- `gc` 命令：应出现 `Frame rate (fps): >0` → 出帧正常
- `dl` + `elr` 组合：dl 后帧率应降为 0，elr 后应恢复 >24fps

---

## 2. 技术方案演进

### 2.1 方案一：FIFO + nohup（已废弃）

**思路**：后台 nohup 启动 nvsipl，通过 FIFO 注入命令，通过 log 文件读取输出。

```bash
mkfifo /storage/zja/nvsipl_stdin_fifo
nohup sh -c "exec 3<>fifo; ./nvsipl_camera ... <&3" > /tmp/nvsipl_parallel_output.log 2>&1 & echo $!
# 注入命令
echo 'gc 10' > /storage/zja/nvsipl_stdin_fifo
# 读取输出
cat /tmp/nvsipl_parallel_output.log
```

**遇到的问题**：

| 问题 | 说明 | 状态 |
|---|---|---|
| QNX `/tmp` 不支持 FIFO | `mkfifo /tmp/xxx` → "No such file or directory" | 改用工作目录 |
| cat fifo → nvsipl 立即退出 | cat 读完 EOF 传给 nvsipl | 改用 `exec 3<>fifo` |
| nohup 全缓冲 | stdout 写入文件时全缓冲，grep 读不到实时数据 | **无法解决** |
| 等 fps 超时 60s | 输出在 buffer 中未刷新到文件 | 同上根因 |
| al 输出读不到 | 同全缓冲问题，al 的结果在 buffer 中 | 同上根因 |

**结论**：nohup 重定向到文件时，QNX 上 nvsipl_camera 的 stdout 变为全缓冲（非 PTY 模式），导致输出延迟数十秒才刷新，无法实时读取交互命令结果。`stdbuf`/`unbuffer` 在 QNX 上不可用。

### 2.2 方案二：PTY Channel（当前方案）

**思路**：使用 Paramiko 的 PTY（伪终端）channel 运行 nvsipl，通过 `channel.send()` 注入命令，`channel.recv()` 实时读取输出。

```python
channel = transport.open_session()
channel.get_pty(width=200, height=50)
channel.exec_command("cd /storage/zja/ && ./nvsipl_camera ...")

# 实时读取输出
data = channel.recv(65536).decode()

# 注入命令
channel.send("gc 10\n")
channel.send("al\n")

# 退出
channel.send("q\n")
channel.close()
```

**优势**：
- PTY 模式下 stdout 自动行缓冲，输出实时可见
- 无需 FIFO、log 文件等中间介质
- 同一 Paramiko transport 支持多 channel 并行（PTY + 普通 exec）
- 执行流程简洁清晰

**验证结果**（2026-08-14）：
- nvsipl 初始化：0.3s（菜单出现）
- gc 10 → fps 出现：2.1s
- al → 像素信息出现：< 5s
- `Sensor ID 10 728 belongs to MIXGROUP_PREDEV, Vertical:2160, horizontal:3840` ✅

---

## 3. 代码变更记录

### 3.1 `backend/app/core/executor_adapter.py`

#### 重写 `_execute_parallel_fault_test`（PTY 方案）

**新流程**：
```
启动(PTY) → 等菜单ready → gc(等fps) → al/ro(等特征输出) → 后续shell命令 → q退出
```

**关键改动**：
- 用 `ssh.open_interactive_channel()` 打开 PTY channel
- 异步 `_read_channel()` 辅助函数：带超时和 stop_pattern 的增量读取
- gc 命令：等待 `Frame rate` 出现（最多 20s）
- al 命令：等待 `Vertical|horizontal|belongs to` 出现（最多 10s）
- 有效输出过滤：跳过菜单提示行（`Enter '...'`）和 fps 行
- 整体超时从 120s → 180s

#### 交互命令输出过滤逻辑

```python
# al 的有效输出提取
for line in cmd_output.split('\n'):
    stripped = line.strip()
    if stripped.startswith("Enter '") or "Frame rate" in stripped:
        continue  # 跳过菜单和 fps
    if stripped in ('-', 'Output'):
        continue
    useful_lines.append(stripped)
```

### 3.2 `backend/app/core/command_parser.py`

#### 修复 Unicode 弯引号匹配

**问题**：Excel 导出的 `'al'` 使用 Unicode 左右弯引号（U+2018/U+2019），但正则中只有 ASCII 引号。

**修复**（pat0）：
```python
# 修复前 - 只有 ASCII 引号
r"""输入(?!命令)\s*[''""'\"]([a-zA-Z][a-zA-Z0-9_ ]*)[''""'\"]"""

# 修复后 - 包含 Unicode 弯引号 ''""
r"输入(?!命令)\s*['\"''""]([a-zA-Z][a-zA-Z0-9_ ]*)['\"''""]"
```

**覆盖的引号字符**：
| 字符 | Unicode | 名称 |
|---|---|---|
| `'` | U+0027 | ASCII 单引号 |
| `"` | U+0022 | ASCII 双引号 |
| `'` | U+2018 | 左单弯引号 |
| `'` | U+2019 | 右单弯引号 |
| `"` | U+201C | 左双弯引号 |
| `"` | U+201D | 右双弯引号 |

#### 其他 command_parser 修复（此前调试中完成）

| 修改 | 说明 |
|---|---|
| "起流" pattern 加严 | `r"起流\s*[：:]\s*"` 必须有冒号，避免 "起流后" 误匹配 |
| nvsipl_input 检测前置 | 在 `extract_all_commands` 之前检测，防止 "输入al" 被提取为 shell 命令 |
| parse_nvsipl_interactive_inputs 只用 main_text | `re.split(r'[①②③...]', text)[0].split('\n')[0]` 避免扫描注释段 |
| Pattern2 加 is_cmd_list 门槛 | 只在 "执行dl/输入gc" 等明确前缀时才用子命令模式扫描 |
| 子命令统一小写 | `cmd_name.lower()` 确保 gc/al/ro 等为小写 |

### 3.3 `backend/app/core/ssh_manager.py`

#### execute 方法重写（此前完成）

**问题**：原版 `exec_command` + `recv_exit_status()` 在 QNX 后台进程不关 channel 时永久阻塞。

**修复**：改为 channel 级 polling + timeout：
```python
channel = transport.open_session()
channel.settimeout(timeout)
channel.exec_command(cmd)
while True:
    if elapsed >= timeout: break
    if channel.exit_status_ready():
        # 读取剩余数据并退出
        break
    # 读取可用数据
    if channel.recv_ready():
        stdout_data += channel.recv(65536)
    time.sleep(0.05)
```

---

## 4. QNX 环境特性备忘

| 特性 | 说明 |
|---|---|
| OS | QNX 8.0 (ARMv9_nVidia-Thor aarch64le) |
| `/tmp` 不支持 FIFO | `mkfifo /tmp/xxx` 失败，需用其他路径 |
| 无 `stdbuf` | 不可用 |
| 无 `unbuffer` | 不可用 |
| `script` 仅 `[-a] [file]` | 不支持 `-q`/`-c`，无法用于无缓冲包装 |
| 有 `tee` | 可用但不解决上游缓冲问题 |
| PTY 模式行缓冲 | nvsipl 在 PTY 下输出实时可见 ✅ |
| SSH 端口 | 22（标准） |
| Paramiko 兼容 | ✅ 直连正常，无 cipher 不兼容问题 |

---

## 5. 已知问题与后续优化

### 5.1 待解决

| 编号 | 问题 | 优先级 | 说明 |
|---|---|---|---|
| P1 | al 输出判定逻辑 | 高 | 需确认 ExpectedResultParser 能正确匹配 `Vertical`/`horizontal` 关键字判 pass |
| P2 | 多 sensor 场景 | 中 | gc 后可能有多路 fps，al 输出多行，需验证 |
| P3 | PTY 方案 + system_ssh 兼容 | 低 | 当 Paramiko 回退到 system ssh 时 PTY 不可用，需 fallback |
| P4 | 残留 nvsipl 进程清理 | 中 | 异常退出时 nvsipl 可能残留，影响下次执行 |

### 5.2 已修复

| 编号 | 问题 | 修复方案 |
|---|---|---|
| F1 | FIFO 在 /tmp 失败 | 改用工作目录 `/storage/zja/` |
| F2 | cat fifo → nvsipl EOF | 改用 `exec 3<>fifo` |
| F3 | Paramiko exec 阻塞 | channel polling + timeout |
| F4 | 全缓冲无法读实时输出 | **改用 PTY channel 方案** |
| F5 | "起流后" 误匹配为命令 | "起流" pattern 必须有冒号 |
| F6 | ro/ed 等误识别 | 限制 pattern2 扫描范围 |
| F7 | Unicode 弯引号不匹配 | pat0 字符类加入 U+2018/2019/201C/201D |
| F8 | al 未被识别为交互步骤 | F7 根因修复后解决 |
| F9 | fps 等待错误流程 | 先 gc 再等 fps（非先等 fps 再 gc） |
| F10 | FIFO 路径双斜杠 | `work_dir.rstrip("/")` |

### 5.3 后续需求

| 编号 | 需求 | 说明 |
|---|---|---|
| R1 | al 输出用于 pass/fail 判定 | 检测是否有 Vertical/horizontal 非零值 |
| R2 | 用例超时自动 kill | 超过 180s 自动终止 nvsipl 并标记 timeout |
| R3 | DEBUG 日志可配置开关 | 上线后关闭 DEBUG 级别日志 |
| R4 | dl/elr 场景验证 | 多步骤 dl→检测fps=0→elr→fps恢复 |

---

## 6. 执行流程图（PTY 方案）

```
┌─────────────────────────────────────────────────────────────┐
│                  _execute_parallel_fault_test                 │
└─────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────┐
│ open_interactive_   │  Paramiko PTY channel
│ channel(nvsipl_cmd) │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ _read_channel(30s)  │  等待 "Enter 'gc" 菜单出现
│ stop: "Enter 'gc"   │
└────────┬────────────┘
         │ ready
         ▼
┌─────────────────────┐
│ channel.send        │  逐条注入交互命令
│ ("gc 10\n")         │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ _read_channel(20s)  │  等待 "Frame rate" 出现
│ stop: "Frame rate"  │  → 出帧确认
└────────┬────────────┘
         │ fps OK
         ▼
┌─────────────────────┐
│ channel.send        │
│ ("al\n")            │
└────────┬────────────┘
         │
         ▼
┌─────────────────────────┐
│ _read_channel(10s)      │  等待 al 特征输出
│ stop: "Vertical|        │  Sensor ID N belongs to...
│  horizontal|belongs to" │  Vertical:2160
└────────┬────────────────┘  horizontal:3840
         │
         ▼
┌─────────────────────┐
│ 过滤有效输出         │  去掉菜单行/fps行
│ → combined_outputs  │  保留像素信息
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ 执行后续 shell 命令  │  (如有故障注入步骤)
│ via _ssh_execute    │  使用同一 transport 的另一个 channel
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ channel.send("q\n") │  退出 nvsipl
│ channel.close()     │
└─────────────────────┘
```

---

## 7. 测试验证

### 7.1 手动验证（2026-08-14）

在 QNX 板端 PTY 方式直接运行：
```
# ./nvsipl_camera -c MIXGROUP_PREDEV_30FPS_MAX96724_CPHY_x4 -m "0 0 0x0100 0" -R -1 -2 -s -0 -Z
Enter 'gc <sensor ID>' to get Sensor custom inteface
-
gc 10                          ← 输入
sensor_id :10
Enter 'les' followed by ...   ← 菜单
...
Sensor10_Out0  Frame rate (fps):  29.4921   ← 出帧
al                             ← 输入
Sensor ID 10 728 belongs to MIXGROUP_PREDEV, Vertical:2160   ← al 有效输出
horizontal:3840                                               ← al 有效输出
```

### 7.2 自动化验证（Paramiko PTY）

```python
# 结果：
# nvsipl ready: 0.3s
# gc 10 → fps: 2.1s
# al → pixel info: < 5s
# al output: "Sensor ID 10 728 belongs to MIXGROUP_PREDEV, Vertical:2160"
#            "horizontal:3840"
# has_pixel_info: True ✅
```

---

## 附录 A：nvsipl_camera 参数说明

| 参数 | 说明 |
|---|---|
| `-c <config>` | 模组配置名称 |
| `-m "x x x x"` | 模组位置掩码 |
| `-R` | 使能通道（大写，功能参数，非退出控制） |
| `-r N` | 延时 N 秒后退出（小写，有此参数为非阻塞型） |
| `-1 -2 -s -0 -Z` | 其他功能参数 |
| `-l` | 列出可用模组名称 |

**阻塞判断**：无 `-r N` 参数 → 阻塞型（需手动 `q` 退出）
