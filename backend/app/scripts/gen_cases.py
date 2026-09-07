#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_cases.py — 把结构化用例 JSON 写入测试用例 xlsx 模板，套用原模板样式。

用法:
  python3 gen_cases.py <cases.json> [--template 模板.xlsx] [--out 输出.xlsx]

cases.json 结构见 examples/sample_cases.json。脚本会:
  1. 复制模板，保留所有表头/列宽/合并/字体/填充/边框样式;
  2. 把用例写入「功能测试」「故障测试」两个 sheet（从 R15 起）;
  3. 用 meta 覆盖封面/修改控制/参考资料/数据统计区/测试基本信息;
  4. 自动填 Total/执行数量统计（用例阶段 Pass/Fail 等执行列留空,只填 Total=用例数）。

设计列: B=ID C=类型 D=方法 E=描述 F=前置条件 G=步骤 H=预期 I=优先级 J=版本变更
执行列: K~P 留空（用例阶段不写）。

三级值机制:
  1. 用户定制值: cases.json 里直接写的具体值, 最高优先;
  2. 默认值: cases.json 顶层 defaults_used 声明引用了哪些默认值(有来源), 脚本汇总成"默认值确认清单";
  3. 占位符: 值为 "<待补充:...>" 的, 视为缺失, 原样写入并最终汇总告警。

生成末尾分别输出: ⚠️占位符待补充 / ℹ️默认值请确认 两份清单。
"""
import sys
import os
import json
import argparse
from copy import copy

try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    print("ERROR: openpyxl not installed. Run: pip install openpyxl", file=sys.stderr)
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.join(HERE, "templates", "模板_测试用例.xlsx")

# ---- 列映射（1-based, 与模板表头一致）----
# B=2 ID, C=3 类型, D=4 方法, E=5 描述, F=6 前置, G=7 步骤, H=8 预期, I=9 优先级, J=10 版本变更
DATA_START_ROW = 15
COL = {
    "id": 2, "type": 3, "method": 4, "desc": 5, "pre": 6,
    "steps": 7, "expected": 8, "priority": 9, "changelog": 10,
}

# ---- 样式常量（从原报告抓取，保持一致）----
FONT_NAME = "宋体"
HEADER_FILL = PatternFill(fill_type="solid", fgColor="FFF7CAAC")  # 表头橙粉
TITLE_FILL = PatternFill(fill_type="solid", fgColor="FFFFF2CC")   # 标题浅黄
THIN = Side(style="thin", color="FF000000")
MEDIUM = Side(style="medium", color="FF000000")

DATA_FONT = Font(name=FONT_NAME, size=9, bold=False)
DATA_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
DATA_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
# 数据行左侧 ID 列用 medium 左边框（与表头一致）
DATA_BORDER_LEFT = Border(left=MEDIUM, right=THIN, top=THIN, bottom=THIN)
# 最右列(P=16)用 medium 右边框
DATA_BORDER_RIGHT = Border(left=THIN, right=MEDIUM, top=THIN, bottom=THIN)

PLACEHOLDER_PREFIX = "<待补充"


def is_placeholder(v):
    return isinstance(v, str) and v.startswith(PLACEHOLDER_PREFIX)


# ---- 客户版(release)措辞过滤 ----
# 版本2(客户发布版)去掉暴露 AI/机器分工、内部判定逻辑的字眼,只留"做什么+怎么判定"的中性表述。
# 版本1(内部版)不过滤,保留三态判定/正则/黑灰名单等给执行agent用。
#
# 设计原则(踩过坑):
#   - 不能按"整行含关键字就删"粗暴处理 —— 命令本体里的 `slog2info | grep`、`./nvsipl_camera -l`
#     是真实命令,客户版必须保留;只有"判定说明"里的 grep -E/grep -F/黑灰名单/三态逻辑才去掉。
#   - 不能把 H 列删空 —— 客户版仍需可观测的预期(生成.raw/故障位置1/帧率30fps等),只是去掉
#     "怎么自动判定"的部分。
#   - 因此采用"整句精确删除 + 片段替换"两条白名单,只动确定的串,不靠模糊关键字。
#
# RELEASE_DROP_PHRASES: 精确的"判定逻辑片段",出现就删(不影响命令本体)
# RELEASE_REPLACE: 旧→新片段替换(中性化措辞)

RELEASE_DROP_PHRASES = [
    # —— 三态判定逻辑说明(整句) ——
    "(以下全部满足才判Pass,AND逻辑,不是任一)",
    "(以下全部满足才判Pass,AND逻辑)",
    "(全部满足才判Pass,AND逻辑)",
    "(以下全部满足才判Pass,AND逻辑)",
    "Pass(以下全部满足才判Pass,",
    "Pass(全部满足才判Pass,",
    "(出现任一即判Fail,不等超时)",
    "(出现任一即判Fail,不等超时):",
    "Fail(黑名单,出现任一即判Fail,不等超时):",
    "Fail(黑名单,出现任一即判Fail,不等超时)",
    "NT(灰名单,判NT留人工复查,不直接判Fail):",
    "NT(灰名单,判NT留人工复查,不直接判Fail)",
    "NT(超时内Pass标志未凑齐且黑名单未出现):",
    "(不是Fail)",
    "留人工复查", "留待复查",
    # —— grep/正则判定说明(注意:只删带 -E/-F/-oP/精确字样的判定说明,不删命令里的 grep nvsipl_camera)——
    "(grep -E \"STREAMING_ERROR.*[:=]\\s*1\"精确匹配,不靠\"置1\"模糊字样)",
    "(grep -E \"STREAMING_ERROR.*[:=]\\s*1\")",
    "(grep -E \"STREAMING_ERROR.*[:=]\\s*0\")",
    "(grep -F \"{sm}\")",
    "(grep -F精确字符串,防正则误匹配)",
    "(grep精确匹配故障标识名+\"[:=]\\s*1\")",
    "(grep -F精确字符串)",
    "(grep精确匹配时间戳关键字)",
    "(grep精确匹配PMIC故障标识+\"[:=]\\s*1\")",
    "(grep精确匹配故障标识+\"[:=]\\s*1\")",
    "(grep -E \"STREAMING_ERROR.*[:=]\\\\s*1\"精确匹配,不靠\"置1\"模糊字样)",
    "(grep -E \"STREAMING_ERROR.*[:=]\\\\s*1\")",
    "(grep -E \"STREAMING_ERROR.*[:=]\\\\s*0\")",
    "(grep -F \"{sm}\")",
    # —— 数值容差判定逻辑 ——
    "(x<1判Pass;x≥1判Fail;提取不到数值判NT)",
    "(正则提取数值后判定)",
    "(正则提取数值后判,不靠grep到\"30fps\"字样)",
    "(grep -oP '\\d+\\.?\\d*(?=fps)'提取数值后判容差,不靠grep到\"30fps\"字样)",
    "(grep -oP '\\d+\\.?\\d*(?=fps)'提取数值后判容差,不靠grep到\"30fps\"字样)",
    "正则提取数值在容差范围内",
    "正则提取数值后判容差",
    "正则提取数值计算",
    "正则提取数值后判",
    # —— 文件判定逻辑 ——
    "且file命令确认为二进制数据(非文本报错重定向)",
    "且file命令确认为二进制数据",
    "且file确认为二进制数据",
    "(非文本报错重定向)",
    # —— 进程残留/防误判说明 ——
    "(防止进程残留导致下一条起流失败误判)",
    "(防止进程残留导致起不来流被误判全Fail(已发生过的真实问题))",
    "避免上一条用例进程未退干净导致本条起流失败被误判",
    "判NT前先清理残留进程重试一次,仍NT才记NT",
    "判NT前先清理残留进程重试一次",
    "判NT前先清理残留进程重试一次注入,仍NT才记NT",
    "判NT前确认注入版.so已正确放置并重试一次",
    "判NT前确认注入版.so已正确放置并重试一次",
    "判NT前先清理残留进程重试一次注入",
    "(可能是环境/时序/进程残留问题)",
    "(可能是环境/时序/进程残留)",
    "(可能是AE未触发或打印字段不同)",
    "(可能是-e参数未生效或打印字段名不同)",
    "(打印格式可能变了)",
    "(可能是脚本路径错/i2c总线错/-n值错)",
    "(脚本路径/总线/地址/-n值)",
    "(可能是脚本路径错/i2c总线错/-n值错)",
    "(i2c总线/地址/寄存器/值是否正确)",
    "(地址选错/寄存器序列不完整)",
    "(脚本路径错/i2c总线错/-n值错)",
    "先判NT复查注入是否生效",
    "先判NT复查注入是否生效(脚本路径/总线/地址/-n值)",
    "先判NT复查注入是否生效(可能是脚本路径错/i2c总线错/-n值错)",
    "先判NT复查so替换是否生效",
    "先判NT复查注入是否生效(i2c总线/地址/寄存器/值是否正确)",
    "先判NT复查注入是否生效(地址选错/寄存器序列不完整)",
    "先判NT复查so替换是否生效",
    "注入版.so未生效(放错目录/未用注入版起流)→故障位不置1,",
    "注入版.so未生效→故障位不置1,",
    "另:注入后ex8查故障位仍=0,",
    "另:注入后故障位仍=0,",
    # —— 起流判定/超时逻辑(客户版简化为中性)—— 由 RELEASE_REPLACE 处理主句,这里删多余括号
    "(功能点出现即输入q退出,不固定等5秒;超时15秒未生成判异常,标注异常并进入下一条)",
    "(功能点出现即输入q退出,不固定等5秒;超时15秒未出现判异常,标注异常并进入下一条)",
    "(功能点出现即输入q退出,不固定等5秒;超时15秒未生成判异常)",
    "(功能点出现即输入q退出,不固定等5秒;超时15秒未出现判异常)",
    "(功能点=exp/gain值变化,出现即继续;每次切换超时15秒未变化判异常)",
    "(超时15秒未出现则判定起流失败,标注异常,执行slay nvsipl_camera清理后进入下一条用例,不死等)",
    "(超时15秒未出现则判定起流失败,标注异常,清理残留进程后进入下一条用例)",
    "(超时30秒未出现则判定起流失败,标注异常,清理残留进程后进入下一条用例)",
    "(超时30秒未出现则判定起流失败,标注异常,执行slay nvsipl_camera清理后进入下一条用例,不死等)",
    "起流前先清理可能残留的进程:在板端执行 slay nvsipl_camera; slay nvsipl_multicast(若存在),",
    "起流前先清理可能残留的进程:在板端执行 slay nvsipl_camera; slay nvsipl_multicast(若存在),避免上一条用例进程未退干净导致本条起流失败被误判",
    # —— M列双产物说明 ——
    "M列备注:同时保存log文本(供grep判定)与终端打印截图(供人查看);7yuv图像画面截图由人工确认",
    "M列备注:同时保存log文本(供grep判定)与终端打印截图(供人查看)",
    ",{M_NOTE}",
    # 容差行尾括号
    "29~31",
    "(待datasheet确认)",
    "(待确认)",
    # 跳板机内部说明(客户版不提ProxyJump)
    ",不写ProxyJump",
    "不写ProxyJump",
    "ProxyJump",
]

# 片段替换(成对: 旧→新),中性化措辞
RELEASE_REPLACE = [
    # 图像判定: "人工确认"→中性
    ("(图像内容是否正常由人工确认)", "图像内容无异常"),
    ("(图像内容由人工确认)", "图像内容无异常"),
    ("(图像内容无花屏/黑屏(人工用7yuv确认,机器不判内容))", "图像内容无花屏/黑屏"),
    ("(人工用7yuv确认,机器不判内容)", ""),
    ("(人工用7yuv确认)", ""),
    ("人工用7yuv确认", "用7yuv确认"),
    # 起流判定句中性化(保留"等帧率打印出现"这种可观测描述,去掉"作为标志/超时判失败"等)
    ("等待终端出现帧率打印或\"streaming\"字样作为起流成功标志", "等待终端出现帧率打印或\"streaming\"字样,确认起流成功"),
    ("等待终端出现各模组帧率打印作为起流成功标志", "等待终端出现各模组帧率打印,确认起流成功"),
    # 功能点退出条件中性化
    ("等待调试目录下生成对应的.raw文件且文件size>0作为功能点出现标志", "等待调试目录下生成对应的.raw文件"),
    ("等待调试目录下生成对应的.yuv文件且文件size>0作为功能点出现标志", "等待调试目录下生成对应的.yuv文件"),
    ("等待终端打印含\"EEPROM\"或内参数据关键字作为功能点出现标志", "等待终端打印内参数据(含EEPROM字样)"),
    ("等待终端打印完整metadata(含时间戳)作为功能点出现标志", "等待终端打印完整metadata(含时间戳)"),
    ("等待各模组帧率打印出现作为功能点出现标志", "等待各模组帧率打印出现"),
    ("给镜头切换白天环境,等待终端打印的exp、gain值发生变化", "给镜头切换白天环境,观察终端打印的exp、gain值变化"),
    ("再切换黑夜环境,等待exp、gain值再次变化", "再切换黑夜环境,观察exp、gain值再次变化"),
    # 用例结束确认中性化(保留"确认进程已终止无残留"这种正常措辞,去掉"防止误判"等)
    ("用例结束确认:输入q退出nvsipl_camera,确认nvsipl_camera(或nvsipl_multicast)进程已终止、无残留,方可进入下一条用例(防止进程残留导致下一条起流失败误判)",
     "用例结束确认:输入q退出nvsipl_camera,确认进程已终止、无残留,方可进入下一条用例"),
    ("用例结束确认:在板端终端A输入q退出,或在终端B执行 slay nvsipl_camera 强制终止,确认nvsipl_camera(或nvsipl_multicast)进程已终止、无残留,方可进入下一条用例",
     "用例结束确认:在板端终端A输入q退出,或在终端B执行 slay nvsipl_camera 强制终止,确认进程已终止、无残留,方可进入下一条用例"),
    # 起流判定行整体替换(故障用例)
    ("起流判定:等待终端出现帧率打印或\"streaming\"字样作为起流成功标志;起流成功后保持终端A运行,不要退出",
     "等待终端出现帧率打印或\"streaming\"字样,确认起流成功后保持终端A运行,不要退出"),
    ("起流判定:等待终端出现各模组帧率打印作为起流成功标志;起流成功后保持终端A运行",
     "等待终端出现各模组帧率打印,确认起流成功后保持终端A运行"),
    # 数值类预期中性化(去掉判定逻辑,保留容差数值)
    ("③按公式(A-B)*32/pow(10,6)正则提取数值计算,帧同步时间差严格<1ms", "③按公式(A-B)*32/pow(10,6)计算,帧同步时间差<1ms"),
    ("②各模组帧率打印出现,正则提取数值在容差范围内:728:30fps±1(29~31);623:30fps±1;031:30fps±1;x5b:30fps±1;x3j:30fps±1",
     "②各模组帧率打印出现,帧率达标:728:30fps;623:30fps;031:30fps;x5b:30fps;x3j:30fps"),
    ("②各模组帧率打印出现", "②各模组帧率打印出现"),
    # Fail行: 去掉退出码强杀逻辑,留报错关键字
    ("终端打印segfault/Segmentation fault/core dumped/Aborted;或nvsipl_camera进程退出码≠0且非slay强杀所致;",
     "终端打印segfault/Segmentation fault/core dumped/Aborted等错误;"),
    ("或nvsipl_camera进程退出码≠0且非slay强杀所致", "进程异常退出"),
    ("或进程退出码≠0且非slay强杀所致", "进程异常退出"),
    ("进程退出码≠0且非slay强杀所致", "进程异常退出"),
    ("或.raw文件生成但size=0(空文件)", "或.raw文件生成但为空文件"),
    ("或帧同步时间差≥1ms", "或帧同步时间差≥1ms"),
    ("或某模组帧率超出容差(如728帧率<29或>31)", "或某模组帧率不达标"),
    # NT行简化
    ("15秒内.raw未生成也无报错→判NT(不是Fail),", "超时.raw未生成也无报错,"),
    ("15秒内.yuv未生成也无报错→判NT(不是Fail),", "超时.yuv未生成也无报错,"),
    ("15秒内终端未打印内参数据也无报错→判NT(不是Fail),", "超时终端未打印内参数据也无报错,"),
    ("15秒内metadata未打印也无报错→判NT(不是Fail),", "超时metadata未打印也无报错,"),
    ("或metadata打印了但提取不到时间差数值→判NT(打印格式可能变了);", "或metadata打印但无法计算时间差;"),
    ("或帧率打印了但提取不到数值→判NT(打印格式可能变了);", "或帧率打印但无法读取数值;"),
    ("注入后30秒内②③未凑齐、且黑名单未出现→判NT(不是Fail),", "注入后故障位未置1也无报错,"),
    ("注入后30秒内②③未凑齐、且黑名单未出现→判NT,", "注入后故障位未置1也无报错,"),
    ("30秒内②③未凑齐、且黑名单未出现→判NT,", "注入后故障位未置1也无报错,"),
    ("注入后ex8查故障位仍=0,", "注入后故障位未置1,"),
    ("注入后故障位仍=0,", "注入后故障位未置1,"),
    ("3、NT(灰名单,判NT留人工复查,不直接判Fail):", "3、异常:"),
    ("3、NT(灰名单,", "3、异常:"),
    ("4、NT:注入后30秒内②③未凑齐、且黑名单未出现→判NT,", "4、异常:注入后故障位未置1也无报错,"),
    ("4、NT:注入后30秒内", "4、异常:注入后"),
    ("3、NT:15秒内", "3、异常:超时"),
    ("3、NT:超时", "3、异常:超时"),
    ("4、NT:", "4、异常:"),
    ("3、NT:", "3、异常:"),
    # Pass行去括号
    ("(全部满足才判Pass,AND逻辑)", ""),
    # 残留词清理
    ("(若存在)", ""),
    ("(供grep判定)", ""),
    ("(供人查看)", ""),
    ("log文本", "log"),
    ("终端打印截图", "截图"),
    ("同时保存log与截图", "保存log与截图"),
    # —— 客户版禁词全量清洗(末道防线) ——
    # 这些词在内部版是判定逻辑用词,客户版一律替换为中性表述或删除
    ("需人工确认", ""),               # 灰名单句尾
    ("人工确认图像内容", "图像内容确认"),
    ("人工确认)", ")"),               # "(若打印含CRC字段,人工确认)" → "(若打印含CRC字段)"
    ("(人工确认)", ""),
    ("人工用7yuv确认", "用7yuv确认"),
    ("7yuv图像画面截图由人工确认", "7yuv图像画面截图确认"),
    ("起流前先清理可能残留的进程:在板端执行 slay nvsipl_camera; slay nvsipl_multicast,",
     "起流前在板端执行 slay nvsipl_camera; slay nvsipl_multicast 清理可能残留的进程,"),
    ("无黑名单报错", "无报错"),
    ("黑名单", "报错关键字"),         # 残留的"黑名单"统一改"报错关键字"
    ("灰名单", "需确认字样"),
    ("判NT前先清理残留进程重试一次注入,仍NT才记NT", "重新执行一次用例确认"),
    ("判NT前先清理残留进程重试一次,仍NT才记NT", "重新执行一次用例确认"),
    ("判NT前先清理残留进程重试一次注入", "重新执行一次用例确认"),
    ("判NT前先清理残留进程重试一次", "重新执行一次用例确认"),
    ("判NT前", "记异常前"),
    ("判NT", "记异常"),
    ("判Pass", "通过"),
    ("判Fail", "判失败"),
    ("残留进程", "进程"),
    ("(grep -F \"{sm}\")", ""),        # 兜底
    ("grep -F", ""),                   # 兜底: 判定说明里残留的 grep -F
    ("grep -E", ""),                   # 兜底
    ("grep -oP", ""),                  # 兜底
    ("精确字符串,防正则误匹配", ""),
    ("精确匹配", ""),
    ("正则提取", ""),
    ("AND逻辑", ""),
    ("OR逻辑", ""),
    ("未凑齐", "未出现"),
    # 句尾/句首多余标点清理(放最后)
    (",,", ","),
    (",,", ","),
    (";;", ";"),
    ("::", ":"),
]

# 客户版还要删的整行(以这些开头的行,判定逻辑专属,客户版不要)
RELEASE_DROP_LINE_PREFIXES = [
    "M列备注:同时保存",
    "  ③图像内容无花屏/黑屏(人工用7yuv确认,机器不判内容)",
]


def to_release_text(text):
    """把一条用例的 G 或 H 文本转成客户发布版(中性措辞)。
    策略: 片段精确替换(REPLACE) + 片段删除(DROP_PHRASES) + 整行删(行首前缀)
          + 正则末道清扫(判定括号残留/grep残留/空括号/重复标点)。
    不靠模糊关键字删整行,避免误删命令本体里的 grep/slay 等。"""
    import re
    if not isinstance(text, str):
        return text
    s = text
    # 1) 片段替换(先做,因为有些替换会改出可删的串)
    for old, new in RELEASE_REPLACE:
        s = s.replace(old, new)
    # 2) 精确片段删除
    for phrase in RELEASE_DROP_PHRASES:
        s = s.replace(phrase, "")
    # 3) 按行首前缀删整行
    lines = s.split("\n")
    out = []
    for ln in lines:
        stripped = ln.lstrip()
        if any(stripped.startswith(p) for p in RELEASE_DROP_LINE_PREFIXES):
            continue
        out.append(ln)
    s = "\n".join(out)
    # 4) 正则末道清扫 ——
    # 4.1 删 grep 判定括号: 形如 ( "...正则..." ,不靠"xx"模糊字样) / ( "xxx") / (grep ...)
    #     只删括号内以 空格+引号 或 grep 或 正则 开头的(判定说明), 不删命令里的(slog2info | grep nvsipl_camera)那种
    s = re.sub(r'\(\s*"[^"]*"[^()]*\)', '', s)          # ( "STREAMING_ERROR..." ,不靠"置1"模糊字样)
    s = re.sub(r'\(\s*grep[^()]*\)', '', s)              # (grep -F "...")
    s = re.sub(r'\(\s*grep[^()]*$', '', s, flags=re.M)   # 行尾 (grep ...
    s = re.sub(r"\(\s*'[^']*'[^()]*\)", '', s)           # ('\d+\.?\d*(?=fps)'提取数值后判容差,)
    # 4.2 判定短语清理
    s = s.replace("不靠\"置1\"模糊字样", "")
    s = s.replace("不靠\"30fps\"字样", "")
    s = s.replace("不靠grep到\"30fps\"字样", "")
    s = s.replace(",精确匹配", "")
    s = s.replace("精确匹配", "")
    s = s.replace("精确字符串,防正则误匹配", "")
    s = s.replace("精确字符串", "")
    s = s.replace("防正则误匹配", "")
    s = s.replace("正则提取数值后判容差", "")
    s = s.replace("正则提取数值后判定", "")
    s = s.replace("正则提取数值后判", "")
    s = s.replace("正则提取数值计算", "")
    s = s.replace("正则提取数值", "")
    s = s.replace("正则匹配", "")
    # 4.2b 数值容差判定括号: (x<1通过;x≥1判失败;提取不到数值记异常) / (数值后判定)
    s = re.sub(r'\(x<1[^()]*\)', '', s)
    s = re.sub(r'\(数值后判定\)', '', s)
    s = re.sub(r'\([^()]*数值后判[^()]*\)', '', s)
    s = s.replace(",数值在容差范围内", "")
    s = s.replace("数值在容差范围内", "")
    # 4.3 文件判定逻辑中性化
    s = s.replace("且file命令确认为二进制数据", "")
    s = s.replace("且file确认为二进制数据", "")
    s = s.replace("且size>0", "")
    s = s.replace(",且size>0", "")
    s = s.replace("size>0", "文件大小正常")
    s = s.replace("size=0", "为空文件")
    s = s.replace("作为功能点出现标志", "")
    s = s.replace("功能点出现即输入q退出,不固定等5秒;", "")
    s = s.replace("功能点出现即", "")
    s = s.replace("不固定等5秒", "")
    s = s.replace("作为起流成功标志", "")
    # 4.4 Pass/Fail 标题行判定逻辑去括号
    s = re.sub(r'Pass\(以下全部满足才通过,[^()]*\)', 'Pass', s)
    s = re.sub(r'Pass\(全部满足才通过[^()]*\)', 'Pass', s)
    s = re.sub(r'Pass\(以下全部满足才通过\)', 'Pass', s)
    s = re.sub(r'Fail\([^()]*出现任一即判失败[^()]*\)', 'Fail', s)
    s = re.sub(r'Fail\(报错关键字[^()]*\)', 'Fail', s)
    s = re.sub(r'NT\(超时内[^()]*未出现[^()]*\)', '异常', s)
    s = re.sub(r'NT\(灰名单[^()]*\)', '异常', s)
    s = s.replace("以下全部满足才通过,不是任一", "以下全部满足")
    s = s.replace("以下全部满足才通过", "以下全部满足")
    # 4.5 异常/NT 行残留
    s = s.replace("→记异常", "→记异常")
    s = s.replace("→判NT", "→记异常")
    s = s.replace("判NT", "记异常")
    s = s.replace("记异常前先清理进程重试一次,仍NT才记NT", "重新执行一次用例确认")
    s = s.replace("记异常前先清理进程重试一次", "重新执行一次用例确认")
    s = s.replace("先记异常复查注入是否生效", "复查注入是否生效")
    s = s.replace("不立即判失败,", "")
    s = s.replace("不立即判失败", "")
    # 4.6 多余标点/空括号
    for _ in range(4):
        s = s.replace(",,", ",").replace(",,", ",")
        s = s.replace(",;", ",").replace(";,", ";")
        s = s.replace(";;", ";").replace("::", ":").replace("。。", "。")
        s = s.replace("( ", "(").replace(" )", ")")
        s = s.replace("()", "").replace("( )", "")
        s = s.replace(",,", ",")
    s = re.sub(r',;', ',', s)                           # ,; → ,
    s = re.sub(r';,', ';', s)                           # ;, → ;
    s = re.sub(r'\(\s*\)', '', s)                       # 空括号
    s = re.sub(r'[,，;；:：]\s*$', '', s, flags=re.M)    # 行尾标点
    s = re.sub(r'\(\s*$', '', s, flags=re.M)            # 行尾残留 (
    # 4.7 连续空行压缩
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"\n[ \t]*\n", "\n", s)
    # 4.8 空编号行(只剩"3、"没内容)删掉
    s = re.sub(r"\n\d+、\s*(?=\n|$)", "", s)
    return s.strip()


def apply_release_variant(wb, sheet_names=None):
    """对已写入的用例做客户版措辞过滤: 遍历各数据sheet的F/G/H列(R15起),逐格过滤。
    F(前置)也过滤,因为前置里可能混入'不写ProxyJump'等内部说明字样。
    sheet_names: 要过滤的sheet名列表;None=自动找所有含用例数据(R15起B列有值)的sheet。"""
    if sheet_names is None:
        sheet_names = [s for s in wb.sheetnames if wb[s].cell(row=DATA_START_ROW, column=COL["id"]).value is not None]
    for sheetname in sheet_names:
        if sheetname not in wb.sheetnames:
            continue
        ws = wb[sheetname]
        r = DATA_START_ROW
        while ws.cell(row=r, column=COL["id"]).value is not None:
            for k in ("pre", "steps", "expected"):
                cell = ws.cell(row=r, column=COL[k])
                cell.value = to_release_text(cell.value)
            r += 1


def copy_fault_template_as(wb, new_name):
    """复制模板里的'故障测试Fault Testing'sheet作为新sheet(用于故障变体B/C/稳定性等),
    手动补全copy_worksheet不复制的东西:合并单元格+列宽。表头/样式会自动复制。
    返回新sheet对象。"""
    src = wb["故障测试Fault Testing"]
    new = wb.copy_worksheet(src)
    new.title = new_name
    # copy_worksheet 不复制合并单元格,手动补
    for mc in src.merged_cells.ranges:
        # 跳过标题行(B2:C3)的合并——新sheet复制的标题也合了,但copy可能已含;统一重建避免遗漏
        new.merge_cells(str(mc))
    # 列宽
    for col_letter, dim in src.column_dimensions.items():
        new.column_dimensions[col_letter].width = dim.width
    # 行高(表头行13/14)
    for r in (13, 14):
        if r in src.row_dimensions:
            new.row_dimensions[r].height = src.row_dimensions[r].height
    return new


def write_case_row(ws, row_idx, case, id_str):
    """把一条用例写入指定行的设计列(B~J)，执行列(K~P)留空。"""
    values = {
        COL["id"]: id_str,
        COL["type"]: case.get("type", ""),
        COL["method"]: case.get("method", ""),
        COL["desc"]: case.get("desc", ""),
        COL["pre"]: case.get("pre", ""),
        COL["steps"]: case.get("steps", ""),
        COL["expected"]: case.get("expected", ""),
        COL["priority"]: case.get("priority", ""),
        COL["changelog"]: case.get("changelog", ""),
    }
    for col_idx, val in values.items():
        cell = ws.cell(row=row_idx, column=col_idx, value=val if val != "" else None)
        cell.font = DATA_FONT
        cell.alignment = DATA_ALIGN
        # 边框: B 列左 medium, J 列右保持 thin(因为 K~P 还在,右边框由 P 列定)
        if col_idx == COL["id"]:
            cell.border = DATA_BORDER_LEFT
        else:
            cell.border = DATA_BORDER
    # 执行列 K~P 留空但要给样式（边框+居中），保证表格完整
    for col_idx in range(11, 17):
        cell = ws.cell(row=row_idx, column=col_idx, value=None)
        cell.font = DATA_FONT
        cell.alignment = DATA_ALIGN
        cell.border = DATA_BORDER_RIGHT if col_idx == 16 else DATA_BORDER

    # 行高: 步骤/前置条件文字长，给足够高度
    max_len = max(len(str(case.get("steps", ""))), len(str(case.get("pre", ""))))
    if max_len > 200:
        ws.row_dimensions[row_idx].height = 200
    elif max_len > 100:
        ws.row_dimensions[row_idx].height = 150
    else:
        ws.row_dimensions[row_idx].height = 90


def write_cases_to_sheet(ws, cases, start_id=1):
    """把用例列表写入 sheet，返回写入条数和占位符清单。"""
    placeholders = []
    n = 0
    for i, case in enumerate(cases):
        row = DATA_START_ROW + i
        id_str = f"{start_id + i:03d}"
        if case.get("id"):  # 若 JSON 显式指定 id 则用之
            id_str = str(case["id"])
        write_case_row(ws, row, case, id_str)
        # 收集占位符（扫描字段内所有 <待补充:xxx>，含嵌入式的）
        import re
        for k in ("type", "method", "desc", "pre", "steps", "expected", "priority"):
            v = case.get(k, "")
            if not isinstance(v, str):
                continue
            for m in re.finditer(r"<待补充[^>]*>", v):
                placeholders.append({"row": row, "id": id_str, "field": k, "placeholder": m.group(0)})
        n += 1
    return n, placeholders


def update_meta_sheets(wb, meta):
    """用 meta 覆盖封面/修改控制/参考资料/数据统计区/测试基本信息。meta 缺失则保留模板原值。

    封面文字在 E 列（E4/E11/E14/E27），对照 Zhiji3.0，写 B 列会导致与模板原有 E 列内容重叠（重影）。
    修改控制表头从 B 列起：B=版本 C=修改内容 D=日期 E=修改者 F=评审人 G=批准人。
    """
    # ---- 封面（E 列，避免重影）----
    cover = wb["文件封面Cover"]
    if meta.get("file_number"):
        cover["E4"] = f"文件编号：{meta['file_number']}"
    if meta.get("title"):
        cover["E11"] = f"{meta['title']}_Software Test Report软件测试报告"
    if meta.get("doc_version"):
        cover["E14"] = f"版本: {meta['doc_version']}"
    # 公司默认保留中科创达，可覆盖
    if meta.get("company"):
        cover["E27"] = f"{meta['company']}"

    # ---- 修改控制（B 列起）----
    dcc = wb["文件修改控制Document Change Control"]
    if meta.get("doc_version") or meta.get("change_content") or meta.get("modifier"):
        dcc["B4"] = meta.get("doc_version", "V1.0")
        dcc["C4"] = meta.get("change_content", "初版测试用例")
        dcc["D4"] = meta.get("revision_date", "")
        dcc["E4"] = meta.get("modifier", "")
        dcc["F4"] = meta.get("reviewer", "")
        dcc["G4"] = meta.get("approver", "")

    # ---- 参考资料 ----
    refs = meta.get("references") or []
    if refs:
        ws = wb["参考資料References"]
        for i, r in enumerate(refs):
            row = 4 + i
            ws.cell(row=row, column=2, value=i + 1)
            ws.cell(row=row, column=3, value=r.get("name", ""))
            ws.cell(row=row, column=4, value=r.get("version", ""))
            ws.cell(row=row, column=5, value=r.get("summary", ""))

    # ---- 数据统计: 测试基本信息(R10 C列) ----
    ds = wb["数据统计Data Statistics"]
    info_lines = []
    if meta.get("os"):
        info_lines.append(f"操作系统/Operating System:{meta['os']}")
    if meta.get("equipment_model"):
        info_lines.append(f"设备型号/Equipment Model:{meta['equipment_model']}")
    if meta.get("dev_board"):
        info_lines.append(f"客户开发板/Customer Development Board:{meta['dev_board']}")
    if meta.get("test_object"):
        info_lines.append(f"测试对象/Testing Object：{meta['test_object']}")
    if meta.get("software_version"):
        info_lines.append(f"软件版本/Software Version:{meta['software_version']}")
    if meta.get("test_version"):
        info_lines.append(f"测试版本/Test Version：{meta['test_version']}")
    if meta.get("test_cycle"):
        info_lines.append(f"测试周期/Testing Cycle:{meta['test_cycle']}")
    if info_lines:
        ds["C10"] = "\n".join(info_lines)


def fix_sheet_count_formula(ws, case_count):
    """扩展测试sheet自身统计区(C4:C11)的COUNTA/COUNTIF公式范围到实际数据末行。

    模板公式如 =COUNTA(B15:B81) 上限81行(约67条),用例超过会漏数。
    动态改成 =COUNTA(B15:B<末行>),保证统计准确不受模板上限限制。
    """
    import re
    if case_count <= 0:
        return
    last_row = DATA_START_ROW + case_count - 1  # 数据末行
    # C4~C11 是统计公式行
    for r in range(4, 12):
        cell = ws.cell(row=r, column=3)
        v = cell.value
        if isinstance(v, str) and v.startswith("="):
            # 把公式里 B15:B<数字> 和 K15:K<数字> 的末行替换为 last_row
            new_v = re.sub(r"(B15:B)\d+", rf"\g<1>{last_row}", v)
            new_v = re.sub(r"(K15:K)\d+", rf"\g<1>{last_row}", new_v)
            if new_v != v:
                cell.value = new_v


def update_statistics(wb, stat_sheets):
    """数据统计sheet: 用公式引用各数据sheet,保持统计链联动(不写硬编码值)。

    模板统计sheet结构固定: R3表头, R4=功能测试, R5=故障测试, R6=合计, R9=Round1, R10-12=基本信息/目标/总结。
    因此统计行只能用R4/R5/R6三行(R4功能/R5故障/R6合计),不能往下扩展(会和R9冲突且J/K/L公式列要维护)。
    多sheet(稳定性+3故障变体)时: R4统计功能sheet,R5统计所有故障相关sheet(稳定性+各变体)之和,R6合计。
    stat_sheets: [(展示名, sheet名, 类别)] 类别='func'归到R4,'fault'归到R5。
    """
    ds = wb["数据统计Data Statistics"]
    func_sheets = [s for (l, s, cat) in stat_sheets if cat == "func"]
    fault_sheets = [s for (l, s, cat) in stat_sheets if cat == "fault"]

    def sum_formula(src_row, sheets):
        """对多个sheet的同一单元格求和: =sheet1!C4+sheet2!C4+..."""
        if not sheets:
            return 0
        parts = [f"'{sn}'!C{src_row}" for sn in sheets]
        return "=" + "+".join(parts)

    # R4 功能测试: 引用功能sheet(s)
    if func_sheets:
        ds.cell(row=4, column=3, value=sum_formula(4, func_sheets))
        ds.cell(row=4, column=4, value="=" + "+".join(f"'{sn}'!C5+'{sn}'!C6+'{sn}'!C8" for sn in func_sheets))
        for offset, src_row in enumerate([5, 6, 7, 8, 9]):
            ds.cell(row=4, column=5 + offset, value=sum_formula(src_row, func_sheets))
    # R5 故障测试: 引用所有故障相关sheet(s)
    if fault_sheets:
        ds.cell(row=5, column=3, value=sum_formula(4, fault_sheets))
        ds.cell(row=5, column=4, value="=" + "+".join(f"'{sn}'!C5+'{sn}'!C6+'{sn}'!C8" for sn in fault_sheets))
        for offset, src_row in enumerate([5, 6, 7, 8, 9]):
            ds.cell(row=5, column=5 + offset, value=sum_formula(src_row, fault_sheets))
    # R6 合计: 模板已有公式 =C4+C5 等,保留不动(J/K/L公式也保留)


def main():
    ap = argparse.ArgumentParser(description="生成测试用例 xlsx")
    ap.add_argument("cases_json", help="结构化用例 JSON 路径")
    ap.add_argument("--template", default=DEFAULT_TEMPLATE, help="模板 xlsx 路径")
    ap.add_argument("--out", help="输出 xlsx 路径（默认与 cases_json 同名 .xlsx）")
    ap.add_argument("--release", action="store_true",
                    help="生成客户发布版: 过滤掉G/H列里暴露AI/机器分工、内部判定逻辑的字眼"
                         "(人工确认/grep/黑灰名单/三态/超时/进程残留等),只留中性表述。"
                         "不加此参数=内部版(保留三态判定等给执行agent用)")
    args = ap.parse_args()

    template = os.path.abspath(args.template)
    if not os.path.exists(template):
        print(f"ERROR: 模板不存在: {template}", file=sys.stderr)
        sys.exit(1)

    with open(args.cases_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    func_cases = data.get("functional_cases", [])
    fault_cases = data.get("fault_cases", [])
    stability_cases = data.get("stability_cases", [])  # 稳定性独立sheet(可选)
    # 故障变体(可选): fault_cases_variant_a/b/c,三变体各一sheet
    fault_a = data.get("fault_cases_variant_a", [])
    fault_b = data.get("fault_cases_variant_b", [])
    fault_c = data.get("fault_cases_variant_c", [])
    defaults_used = data.get("defaults_used", [])

    wb = openpyxl.load_workbook(template)

    all_ph = []  # 收集所有sheet占位符
    stat_sheets = []  # [(展示名, sheet名, 类别'func'/'fault')] 供数据统计sheet引用
    sheet_id_seq = 1  # ID 全局接续(功能→稳定性→故障A→故障B→故障C)
    fault_id_from_start = meta.get("fault_id_from_start", False)

    # 1) 功能测试 sheet(模板自带)
    func_n, func_ph = write_cases_to_sheet(wb["功能测试Functional Testing"], func_cases, start_id=1)
    all_ph += func_ph
    if func_n:
        fix_sheet_count_formula(wb["功能测试Functional Testing"], func_n)
        stat_sheets.append(("功能测试", "功能测试Functional Testing", "func"))
        sheet_id_seq = 1 + func_n  # 下一个sheet从 func_n+1 接续

    # 2) 稳定性测试 sheet(若JSON有stability_cases,复制故障模板新建)
    stab_n = 0
    if stability_cases:
        stab_ws = copy_fault_template_as(wb, "稳定性测试Stability Testing")
        stab_start = 1 if fault_id_from_start else sheet_id_seq
        stab_n, stab_ph = write_cases_to_sheet(stab_ws, stability_cases, start_id=stab_start)
        all_ph += stab_ph
        if stab_n:
            fix_sheet_count_formula(stab_ws, stab_n)
            stat_sheets.append(("稳定性测试", "稳定性测试Stability Testing", "fault"))
            sheet_id_seq = stab_start + stab_n

    # 3) 故障变体 sheet(三变体各一sheet,复制故障模板新建)
    #    若JSON给了fault_cases(旧格式,单一变体),写入原"故障测试Fault Testing"sheet
    #    若给了fault_cases_variant_a/b/c,写入复制的"故障测试变体A/B/C"sheet
    variant_specs = []  # [(变体名, cases, sheet名)]
    if fault_a or fault_b or fault_c:
        if fault_a:
            variant_specs.append(("故障测试变体A", fault_a, "故障测试变体A Fault Testing Variant A"))
        if fault_b:
            variant_specs.append(("故障测试变体B", fault_b, "故障测试变体B Fault Testing Variant B"))
        if fault_c:
            variant_specs.append(("故障测试变体C", fault_c, "故障测试变体C Fault Testing Variant C"))
    elif fault_cases:
        # 旧格式降级:单一故障sheet
        variant_specs.append(("故障测试", fault_cases, "故障测试Fault Testing"))

    fault_total = 0
    for label, cases, sheetname in variant_specs:
        # 变体A用模板自带sheet(若名字是原故障测试),其余复制新建
        if sheetname == "故障测试Fault Testing":
            ws = wb[sheetname]
        else:
            ws = copy_fault_template_as(wb, sheetname)
        f_start = 1 if fault_id_from_start else sheet_id_seq
        fn, fph = write_cases_to_sheet(ws, cases, start_id=f_start)
        all_ph += fph
        fault_total += fn
        if fn:
            fix_sheet_count_formula(ws, fn)
            stat_sheets.append((label, sheetname, "fault"))
            sheet_id_seq = f_start + fn

    # 若用了故障变体模式(故障测试变体A/B/C),模板自带的"故障测试Fault Testing"sheet是空的,删掉
    if any("变体" in s for _, s, _ in stat_sheets):
        if "故障测试Fault Testing" in wb.sheetnames and wb["故障测试Fault Testing"].cell(row=DATA_START_ROW, column=COL["id"]).value is None:
            del wb["故障测试Fault Testing"]

    # ---- 重排sheet顺序: 测试case的sheet(功能/稳定性/故障变体)排在附录前面 ----
    # copy_worksheet默认把新sheet加到末尾(附录之后),需要重排:
    # 顺序= 封面/修改控制/参考/统计/功能/稳定性/故障变体A/B/C/附录/模板修改控制
    front = ["文件封面Cover", "文件修改控制Document Change Control",
             "参考資料References", "数据统计Data Statistics",
             "功能测试Functional Testing"]
    # 中段:稳定性+故障变体(按生成的stat_sheets顺序)
    middle = [s for _, s, _ in stat_sheets if s != "功能测试Functional Testing"]
    back = ["附录1Appendix 1", "模板修改控制"]
    desired = [s for s in (front + middle + back) if s in wb.sheetnames]
    # 把任何遗漏的sheet也加上(放末尾,防漏)
    for s in wb.sheetnames:
        if s not in desired:
            desired.append(s)
    # 用 wb._sheets 重排(openpyxl内部)
    wb._sheets = [wb[s] for s in desired]

    # 元信息 + 统计
    update_meta_sheets(wb, meta)
    update_statistics(wb, stat_sheets)

    # 客户发布版: 过滤G/H列的AI/机器分工字眼(内部判定逻辑)
    if args.release:
        apply_release_variant(wb, [s for _, s, _ in stat_sheets])

    out = args.out or os.path.splitext(args.cases_json)[0] + ".xlsx"
    wb.save(out)

    # 汇总报告
    variant = "客户发布版(已过滤AI/机器分工字眼)" if args.release else "内部版(保留三态判定供执行agent用)"
    print(f"✅ 已生成[{variant}]: {out}")
    print(f"   功能测试用例: {func_n} 条")
    if stab_n:
        print(f"   稳定性测试用例: {stab_n} 条")
    print(f"   故障测试用例: {fault_total} 条")

    # 1) 占位符清单（缺失，必须补；去重显示）
    if all_ph:
        # 去重：同一种占位符文本只列一次，但统计总出现次数
        from collections import Counter
        ph_counter = Counter(p["placeholder"] for p in all_ph)
        print(f"\n⚠️  共 {len(all_ph)} 处【占位符】待人工补充（不补用例无法执行）:")
        for ph, cnt in ph_counter.most_common():
            tag = f" (×{cnt})" if cnt > 1 else ""
            print(f"   - {ph}{tag}")
    else:
        print("\n   ✓ 无占位符。")

    # 2) 默认值确认清单（有值，请确认是否适用）
    if defaults_used:
        print(f"\nℹ️  共 {len(defaults_used)} 项【默认值】请确认是否适用本项目:")
        for d in defaults_used:
            field = d.get("field", "?")
            val = d.get("default_value", "?")
            src = d.get("source", "")
            note = d.get("note", "")
            applies = d.get("applies_to", "")
            print(f"   - {field}: {val}  [{src}]")
            if applies:
                print(f"     适用: {applies}")
            if note:
                print(f"     提示: {note}")
    else:
        print("   ✓ 未引用默认值（所有值均为用户定制）。")


if __name__ == "__main__":
    main()
