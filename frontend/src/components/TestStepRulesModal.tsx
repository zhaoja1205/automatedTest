/**
 * 「测试步骤」编写规则说明弹窗。
 *
 * 内容与后端 CommandParser / 统一执行器的实际行为保持一致，
 * 帮助用例编写者写出能被正确识别、并按预期终端执行的步骤。
 */
import type { ReactNode } from 'react'
import { Alert, Collapse, Modal, Space, Tag, Typography } from 'antd'

interface Props {
  open: boolean
  onClose: () => void
}

function Code({ children }: { children: string }) {
  return (
    <pre
      style={{
        margin: '6px 0',
        padding: '8px 10px',
        background: '#f6f8fa',
        border: '1px solid #e5e7eb',
        borderRadius: 4,
        fontSize: 12,
        lineHeight: 1.6,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
      }}
    >
      {children}
    </pre>
  )
}

function Item({ children }: { children: ReactNode }) {
  return <div style={{ margin: '4px 0', fontSize: 13, lineHeight: 1.8 }}>{children}</div>
}

const { Text } = Typography

export default function TestStepRulesModal({ open, onClose }: Props) {
  const sections = [
    {
      key: 'format',
      label: '1. 基本格式',
      children: (
        <>
          <Item>
            • 编号要写在<Text strong>行首</Text>，支持 <Text code>1.</Text> <Text code>1、</Text>
            <Text code>1．</Text> 三种写法；建议每条步骤单独一行。没有编号时，整段文本会被当作一步。
          </Item>
          <Item>
            • 编号建议从 1 开始连续书写；「重复N-M」「反复起流」都按解析后的步骤顺序回跳。
          </Item>
          <Item>
            • 一个编号对应一条主命令。同一步内需要执行多条命令时，可分行书写：至少两行，
            且每行以 <Text code>sudo ./</Text>、<Text code>./</Text>、<Text code>nvsipl_camera</Text>、
            <Text code>fault_simulation</Text>、<Text code>i2cmastercmd</Text>、<Text code>i2ctransfer</Text>、
            <Text code>i2cget</Text>、<Text code>i2cset</Text>、<Text code>devopen</Text>、
            <Text code>devclose</Text>、<Text code>scp</Text>、<Text code>cat</Text>、
            <Text code>echo</Text>、<Text code>export</Text>、<Text code>source</Text> 等命令开头，
            系统会拆成多条依次执行。
          </Item>
          <Code>{`1. 执行以下命令：
./run_test.sh --case 1
./run_test.sh --case 2`}</Code>
          <Item>
            • 行内的 <Text code>①②③</Text> 及其后的内容、<Text code>注：</Text> 之后的内容不会执行，
            可用于补充说明。<Text code>①</Text> 这类带圈数字是<Text strong>注释标记，不是步骤编号</Text>；
            步骤编号请使用 <Text code>1.</Text> / <Text code>1、</Text>。
          </Item>
          <Item>
            • 中英文冒号（<Text code>:</Text> / <Text code>：</Text>）都可以；中文引号会自动转换为英文引号；
            命令末尾的中文句号、逗号、分号等标点会被自动清理。
          </Item>
        </>
      ),
    },
    {
      key: 'command',
      label: '2. 命令步骤怎么写',
      children: (
        <>
          <Item><Text strong>最稳妥：所有命令都加显式引导词</Text></Item>
          <Code>{`1. 执行命令：ls -l /root/test
2. 起流：./nvsipl_camera -c /root/cfg.json -m "0x0001" -r 5
3. 测试指令：i2ctransfer -f -y 30 w2@0x36 0x30 0x1a`}</Code>
          <Item>
            始终信任的前缀：<Text code>执行命令：</Text> <Text code>需执行的命令：</Text>
            <Text code>所执行命令：</Text> <Text code>指令：</Text> <Text code>起流：</Text>
            <Text code>测试指令：</Text>
          </Item>
          <Item>
            也可使用 <Text code>命令：</Text> <Text code>输入命令：</Text>
            <Text code>故障注入：</Text> <Text code>注入故障：</Text>
            <Text code>故障恢复：</Text> <Text code>恢复故障：</Text>，
            但这些写法仍要求命令里包含可执行关键字（如 <Text code>./</Text>、<Text code>sudo</Text>、
            <Text code>echo</Text>、<Text code>i2c</Text> 等）。
          </Item>
          <Item><Text strong>不带前缀时，仅以下形式能直接识别</Text></Item>
          <Code>{`1. ./run_test.sh --case 1
2. sudo ./run_test.sh --case 1
3. nvsipl_camera -c cfg.json -m "0x0001" -r 5
4. i2cmastercmd -w 0x1a 0x10 0x01
5. cd /root/test
6. scp /root/a.bin root@192.168.1.2:/tmp/
7. devopen /dev/video0
8. devclose /dev/video0
9. export CAM_ROTATE_CFG_PATH=/root/cfg.json
10. source /root/env.sh
11. \`ls -l /root\`
12. 故障注入：sudo ./fault.sh -i 7`}</Code>
          <Item>
            <Text type="warning">注意：</Text><Text code>ls</Text>、<Text code>echo</Text>、
            <Text code>cat</Text>、<Text code>mkdir</Text>、<Text code>sudo chmod</Text>、
            <Text code>i2ctransfer</Text> 等裸命令<Text strong>不会</Text>自动识别，
            请加前缀写成 <Text code>执行命令：ls -l /root</Text>。
          </Item>
          <Item>
            • 两个例外：① 同一步骤的多行命令块中，以命令关键字开头的行会被直接执行；
            ② 步骤以终端标签开头时，标签后的正文整体按命令处理（见第 3 节）。
          </Item>
          <Item>
            • <Text code>export VAR=value</Text>、<Text code>source /path/env.sh</Text> 会在当前终端执行；
            所有步骤都运行在持久化 Shell 中，环境变量会一直保留在该终端，直到用例结束。
            注意终端之间互不共享，发往其他终端的命令看不到这里的变量。
          </Item>
          <Item>
            <Text type="warning">注意：</Text>隐式写法要求命令中包含可执行关键字，
            否则会被当作说明文字跳过。拿不准时加「执行命令：」前缀。
          </Item>
        </>
      ),
    },
    {
      key: 'terminal',
      label: '3. 终端与多终端',
      children: (
        <>
          <Item>
            • 没有写终端标签的步骤默认发给 <Text code>终端A</Text>。
          </Item>
          <Item>
            • 步骤里只要出现「终端A」「终端B」「终端2」等字样，就识别为该终端——
            不限写在开头，也不要求后面带冒号。支持 <Text code>终端A：命令</Text>、
            <Text code>[终端B] 命令</Text>、<Text code>（终端B）</Text>、<Text code>A&gt;</Text>、
            <Text code>在终端D执行命令：...</Text>，以及命令末尾标注
            <Text code>执行命令：./tool --flag（终端E）</Text>。
          </Item>
          <Item>
            • 旧写法 <Text code>另一个终端执行：命令</Text>、<Text code>第二个终端</Text>、
            <Text code>辅终端</Text> 仍兼容，统一归为 <Text code>终端B</Text>；
            建议使用冒号形式，不要用引号包裹，避免多余的引号被带入命令。
          </Item>
          <Code>{`1. 终端A：执行命令：./nvsipl_camera -c cfg.json -m "0x0001"
2. 终端B：执行命令：sudo ./fault_simulation_728.sh -i 7 -a 0x1a -n 5
3. 输入 gc 0
4. 终端B：cat /tmp/fault.log
5. [终端C] ls /tmp
6. A> pwd`}</Code>
          <Item>
            • 同一步骤里可以写多个终端：按终端字样出现的位置切分，各管其后的命令。
          </Item>
          <Code>{`1. 终端A：执行命令：./nvsipl_camera -c cfg.json -m "0x0001"
   终端B：执行命令：sudo ./fault_simulation_728.sh -i 7`}</Code>
          <Item>
            • 每个终端对应一个独立的持久化 Shell：环境变量、工作目录、sudo 凭证都只在各自终端内有效；
            阻塞型前台程序（如不带 <Text code>-r</Text> 的 nvsipl_camera）也属于启动它的终端。
          </Item>
          <Item>
            <Text type="warning">注意：</Text>终端标签<Text strong>只作用于当前步骤</Text>，
            不会延续到下一步。后续步骤若要发往同一终端，必须再次写上标签，
            例如起流在终端A，最后的退出也要写 <Text code>终端A：输入 q</Text>。
          </Item>
          <Item>
            • 标签取单个字母、数字或中文数字（如 <Text code>终端A</Text>、<Text code>终端2</Text>、
            <Text code>终端乙</Text>）；「终端上」「终端中」等普通词不会被当作终端。
          </Item>
          <Item>
            • 步骤以终端标签开头时，标签后的正文会整体视为命令，因此
            <Text code>终端B：ls /tmp</Text>、<Text code>终端B：echo hi</Text> 也能执行。
          </Item>
        </>
      ),
    },
    {
      key: 'dir',
      label: '4. 目录与前置条件',
      children: (
        <>
          <Item><Text strong>切换远端工作目录</Text></Item>
          <Code>{`1. 进入测试目录
2. 进入目录 /opt/camera/test
3. cd /root/nvsipl_test`}</Code>
          <Item>
            • 「进入测试目录 / 进入调试目录 / 进入目录 / 进入工作目录」会切换当前终端的工作目录：
            优先使用「工作区配置 → 默认远端路径」，未配置时取步骤文本中的绝对路径。
            两者都没有时，该步骤不会被识别为切目录。
          </Item>
          <Item>
            • 目录切换在该终端的持久化 Shell 中生效，后续同一终端的命令都在该目录下执行，
            <Text strong>不会</Text>再拼接 <Text code>cd &lt;目录&gt; &amp;&amp; &lt;命令&gt;</Text>。
            其他终端不受影响，需要在其他终端切目录时请带上对应的终端标签。
          </Item>
          <Item>
            • <Text code>cd /path</Text> 同样会切换当前终端的工作目录。
          </Item>

          <Item><Text strong>前置条件字段</Text></Item>
          <Code>{`echo ready; insmod /root/camera.ko; MANUAL_CONFIRM 确认板端已上电`}</Code>
          <Item>
            • 多条前置命令用英文分号 <Text code>;</Text> 分隔，原样下发，且不经过测试步骤的命令解析；
            中文分号 <Text code>；</Text> 不作为分隔符。
          </Item>
          <Item>
            • <Text code>MANUAL_CONFIRM 说明文字</Text> 会弹出人工确认框，必须写成独立的一段；
            任一条命令返回码非 0 时，该用例直接判 Fail，测试步骤不再执行。
          </Item>
          <Item>
            • 工作区中关闭「执行前置条件」时，前置条件整体不执行。
          </Item>
        </>
      ),
    },
    {
      key: 'nvsipl',
      label: '5. nvsipl 交互命令',
      children: (
        <>
          <Code>{`1. 执行命令：./nvsipl_camera -c cfg.json -m "0x0001"
2. 执行 gc 0, dl 0, dl 2, el 3
3. 输入 'ro'
4. 输入 q`}</Code>
          <Item>
            • 支持写法：<Text code>输入 gc</Text>、<Text code>输入 gc 0</Text>、
            <Text code>输入 'ro'</Text>、<Text code>执行 dl 0, dl 2, el 3</Text>、
            <Text code>发送 al</Text>、<Text code>输入 q</Text>。
          </Item>
          <Item>
            • 支持的子命令：<Text code>gc</Text> <Text code>dl</Text> <Text code>dlo</Text>
            <Text code>el</Text> <Text code>elr</Text> <Text code>les</Text>
            <Text code>lds</Text> <Text code>cm</Text> <Text code>ckf</Text>
            <Text code>ro</Text> <Text code>al</Text> <Text code>ed</Text>
            <Text code>th</Text> <Text code>df</Text> <Text code>bp</Text>
            <Text code>sr</Text> <Text code>hs</Text> <Text code>ex</Text> <Text code>q</Text>。
          </Item>
          <Item>
            • 一条步骤里要多条子命令时，用 <Text code>执行 dl 0, dl 2, el 3</Text> 或
            <Text code>发送 ...</Text> 的写法；<Text code>输入 dl 0, dl 2</Text> 只会取到第一条，
            其余子命令请拆成多个步骤。
          </Item>
          <Item>
            • 可在交互输入步骤里指定本次等待的板端输出特征，超时时间可选：
            <Text code>输入 gc 0，等待输出：Frame rate，超时20秒</Text>。
            也可以用 <Text code>/.../</Text> 写正则，如
            <Text code>等待输出:/Frame rate[^:]*:\s*[\d.]+/</Text>；
            不写 <Text code>超时</Text> 时沿用该子命令的内置默认超时。
            配置作用于该步骤的最后一个交互子命令。
          </Item>
          <Item>
            • <Text strong>交互输入只对「阻塞型起流」有效</Text>：不带 <Text code>-r</Text> 的
            nvsipl_camera 启动后会立即返回，后续 <Text code>输入</Text> 步骤会发送给该终端上运行中的进程；
            <Text code>q</Text> 用于退出并回收退出码。
          </Item>
          <Item>
            • 带 <Text code>-r N</Text> 的起流会在 N 秒后自动退出，进程退出后后续
            <Text code>输入</Text> 不再能写入它；需要交互的用例请使用不带 <Text code>-r</Text> 的阻塞模式。
            大写 <Text code>-R</Text> 是功能参数，与是否阻塞无关。
          </Item>
          <Item>
            • 交互输入要写在<Text strong>同一个终端</Text>的步骤上。起流在终端A、输入却默认发往终端A；
            如果起流写在终端B，后续输入也要写 <Text code>终端B：输入 gc 0</Text>。
          </Item>
          <Item>
            • 系统<Text strong>不会自动注入 gc</Text>；只有步骤里显式写了
            <Text code>输入 gc</Text>、<Text code>输入 gc 0</Text> 或
            <Text code>执行 gc 0, ...</Text>，才会发送 gc 命令。
          </Item>
          <Item>
            • 用例结束时系统会对仍在运行的前台程序尝试发送 <Text code>q</Text>；
            建议在步骤里显式写 <Text code>输入 q</Text>，以便及时回收退出码并让日志顺序更清晰。
          </Item>
        </>
      ),
    },
    {
      key: 'repeat',
      label: '6. 重复与压力测试',
      children: (
        <>
          <Code>{`1. 执行命令：./nvsipl_camera -c cfg.json -m "0x0001"
2. 输入 gc 0
3. 输入 q
4. 重复1-3

5. 执行命令：./nvsipl_camera -c cfg.json -m "0x0001"
6. 输入 gc 0
7. 输入 q
8. 反复起流5次`}</Code>
          <Item>
            • 重复范围：<Text code>重复1-3</Text>、<Text code>重复1-3步骤</Text>、
            <Text code>重复第1~3步</Text>、<Text code>重复1到3</Text>；
            单步：<Text code>重复步骤1</Text>、<Text code>重复第1步</Text>。
          </Item>
          <Item>
            • 一条重复指令会把起始步骤到本指令之前的内容<Text strong>再执行一次</Text>（共 2 轮）。
            需要更多轮次可写多条重复指令。
          </Item>
          <Item>
            • 回跳只使用<Text strong>起始编号</Text>，结束编号仅用于提示；从起始步骤会一直执行到本指令之前。
            因此重复指令应紧跟在重复范围的最后一步之后，不要把范围外的步骤夹在中间。
          </Item>
          <Item>
            <Text type="warning">注意：</Text>不要写成 <Text code>重复步骤1-3</Text>——
            该写法会被解析为「重复第 1 步」。正确写法是 <Text code>重复1-3</Text>、
            <Text code>重复1-3步骤</Text> 或 <Text code>重复第1~3步</Text>。
          </Item>
          <Item>
            • 反复起流：<Text code>反复起流10次</Text>、<Text code>重复起流5次</Text>、
            <Text code>循环执行5次</Text>（反复 / 重复 / 循环 + 起流 / 启动 / 执行 / 运行 + N次）。
            系统会回跳到本指令之前最近的 nvsipl_camera 起流命令，重新执行到本指令处；
            N 是总轮数（首次执行 + N-1 次回跳）。前面没有起流命令时该指令会被跳过。
          </Item>
          <Item>
            • 阻塞型起流做反复起流时，请在「反复起流N次」之前显式写 <Text code>输入 q</Text>，
            让每轮都能退出后重新启动；使用带 <Text code>-r</Text> 的起流则无需 q。
          </Item>
          <Item>
            • 统一执行器下，重复指令<Text strong>不再有模式限制</Text>；
            但重复范围只能指向当前步骤之前的步骤，否则会被判为无效并跳过。
          </Item>
          <Item>
            • 步骤序号从 1 开始，指解析后的步骤顺序；建议重复范围只包含命令、输入和等待步骤。
          </Item>
        </>
      ),
    },
    {
      key: 'wait',
      label: '7. 等待与延时',
      children: (
        <>
          <Code>{`1. 终端A：执行命令：./run_test.sh --case 1
等待2秒
2. 等待 1.5s
3. 等待 1 分钟
4. wait 2s`}</Code>
          <Item>
            • 支持 <Text code>等待2秒</Text>、<Text code>等待 2 秒钟</Text>、
            <Text code>延时1.5s</Text>、<Text code>等待1分钟</Text>、<Text code>wait 2s</Text> 等写法，
            单位支持毫秒、秒、分钟。
          </Item>
          <Item>
            • 只写等待的步骤（如 <Text code>等待2秒</Text>）不会下发命令，只暂停指定时长。
          </Item>
          <Item>
            • 写在命令步骤末尾的等待会在该步骤的所有命令执行完后生效；
            同一段文本里的多处等待会累加，单步最长等待 600 秒。
          </Item>
          <Item>
            • <Text code>sleep 3</Text> 是一条可执行命令，不是等待指令；不要同时写
            <Text code>sleep 3</Text> 和 <Text code>等待3秒</Text>，否则容易重复等待。
          </Item>
        </>
      ),
    },
    {
      key: 'manual',
      label: '8. 人工操作与人工确认',
      children: (
        <>
          <Code>{`1. 手动切换 Camera 通道
2. 人为手动拔插 camera 线缆
3. MANUAL_CONFIRM 检查屏幕是否有显示异常`}</Code>
          <Item>
            • 含「人为手动、手动切换、手动操作、手动拔、手动插、人工操作、人工切换、人为操作、
            物理操作、拔插、插拔」的步骤会被标记为人工操作，<Text strong>不会自动下发</Text>，
            仅在执行日志和界面提示操作人员。
          </Item>
          <Item>
            • <Text code>MANUAL_CONFIRM</Text> 必须大写并写在<Text strong>步骤开头</Text>
            （前置条件中则写在某一段开头），执行到此步骤时前端弹出「确认 Pass / 确认 Fail」；
            选择 Fail 时该用例判 Fail 并停止后续步骤。
          </Item>
        </>
      ),
    },
    {
      key: 'skip',
      label: '9. 会被跳过的内容与 NA',
      children: (
        <>
          <Item>• <Text code>ssh ...</Text> 连接命令：由系统管理连接，步骤开头的 ssh 命令会跳过。</Item>
          <Item>
            • 以 <Text code>注：</Text> <Text code>注意：</Text> <Text code>备注：</Text>
            <Text code>说明：</Text> <Text code>Note:</Text> 或 <Text code>①</Text> 开头的步骤视为注释。
          </Item>
          <Item>
            • 纯英文说明（无中文、长度 ≥ 10 且没有可执行命令），以及「查看 / 打开 / 确认 / 验证 / 检查 /
            scp出来」等描述性文字且不含命令的步骤，会被跳过。
          </Item>
          <Item>
            • 无法识别的步骤会被标记为「未识别步骤（已跳过）」，不影响执行，但也不会下发命令；
            可点击行内 <Tag color="purple">AI</Tag> 按钮解析后再预览。
          </Item>
          <Item>
            • 用例任意字段出现 <Text code>待写入</Text> <Text code>方案待写入</Text>
            <Text code>验证方案待写入</Text> <Text code>待补充</Text> <Text code>待完善</Text>
            <Text code>暂不测试</Text> <Text code>不适用</Text> <Text code>TBD</Text>
            <Text code>N/A</Text> <Text code>TODO</Text> 或整个字段只有 <Text code>NA</Text> 时，
            整条用例自动标记为 NA，不执行。
          </Item>
        </>
      ),
    },
    {
      key: 'ai',
      label: '10. AI 重写测试步骤',
      children: (
        <>
          <Item>
            • 点击「测试步骤」列内的 <Tag color="purple">AI</Tag> 按钮，AI 会把当前步骤改写为
            程序可识别的规范写法，不会改动原有测试意图、命令和执行顺序。
          </Item>
          <Item>
            • 原文中的 <Text code>①②③</Text> 属于注释，AI 会改写为 <Text code>注：...</Text>；
            重写结果只使用 <Text code>1.</Text> <Text code>2.</Text> 等普通数字编号，
            不会输出带圈数字作为步骤编号。
          </Item>
          <Item>
            • 改写完成后会以 GitHub 风格差异视图（红色为原文删除、绿色为重写新增）
            展示前后步骤，人工确认无误后再点击「替换测试步骤」。
          </Item>
          <Item>
            • 重写后会立即用规则解析器校验，并提示仍无法识别的步骤；
            此时可保留原步骤手动调整。
          </Item>
          <Item>
            • 上传用例后的后台解析仍采用「规则先行 + AI 兜底」；
            这里的 AI 按钮只针对单条用例重写文本。
          </Item>
        </>
      ),
    },
    {
      key: 'faq',
      label: '11. 常见问题',
      children: (
        <>
          <Item>
            <Text strong>Q：命令没被执行？</Text>
            <br />
            先点该行的命令预览按钮，确认步骤是否被识别以及命令归属的终端。若显示「未识别步骤」，
            改用 <Text code>执行命令：命令</Text> 的显式写法，或点击行内 AI 按钮重写步骤。
          </Item>
          <Item>
            <Text strong>Q：-r 和 -R 有什么区别？</Text>
            <br />
            小写 <Text code>-r N</Text> 表示运行 N 秒后自动退出，属于非阻塞起流；
            <Text code>-R</Text> 是功能参数，不控制退出。需要人工/脚本交互的用例应使用不带
            <Text code>-r</Text> 的阻塞模式，否则进程退出后 <Text code>输入</Text> 步骤无法写入。
          </Item>
          <Item>
            <Text strong>Q：输入 gc 后没有反应？</Text>
            <br />
            检查三点：前方是否有不带 <Text code>-r</Text> 的阻塞型起流；输入步骤是否写在同一终端
            （必要时写 <Text code>终端B：输入 gc 0</Text>）；是否把多条子命令写成了
            <Text code>输入 dl 0, dl 2</Text>（只会取第一条，请改用 <Text code>执行 dl 0, dl 2</Text>）。
          </Item>
          <Item>
            <Text strong>Q：重复指令没有按预期执行？</Text>
            <br />
            确认重复范围指向当前步骤之前；重复指令要紧跟在范围最后一步之后；一条指令只额外执行一次；
            <Text code>反复起流N次</Text> 前面必须有起流命令。
          </Item>
          <Item>
            <Text strong>Q：终端B 的命令跑到终端A 了？</Text>
            <br />
            终端标签只作用于当前步骤，不会延续。需要后续步骤继续在终端B执行时，每一步都要写
            <Text code>终端B：...</Text>。
          </Item>
          <Item>
            <Text strong>Q：多条命令能写在同一行吗？</Text>
            <br />
            可以用 <Text code>;</Text> 连接，但它会被当作一条 shell 命令行执行，出错时难以定位。
            建议拆成多个编号步骤，或写成同一步骤下的多行命令。
          </Item>
          <Item>
            <Text strong>Q：前置条件为什么不执行？</Text>
            <br />
            检查是否用英文分号 <Text code>;</Text> 分隔、工作区是否开启「执行前置条件」、
            以及是否有命令返回非 0 退出码（会导致用例直接 Fail）。
          </Item>
          <Item>
            <Text strong>Q：sudo 命令的密码在哪里配置？</Text>
            <br />
            在工作区配置中设置 sudo 密码，执行时自动注入；命令预览中不会显示密码。
          </Item>
          <Item>
            <Text strong>Q：命令末尾的中文标点有影响吗？</Text>
            <br />
            句号、逗号、分号等尾部标点会被自动清理，但建议不要写在命令中。
          </Item>
        </>
      ),
    },
  ]

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={900}
      title="测试步骤编写规则"
      styles={{ body: { paddingTop: 12, maxHeight: '76vh', overflow: 'auto' } }}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="所有步骤都在「多终端持久化 Shell」中执行：每个终端一个会话，环境变量、工作目录和 sudo 凭证在该终端内保留。"
        description="写法越规范，识别越准确。编写完成后，点击用例行的命令图标可以预览最终下发到板端的完整命令；执行中可在「板端实时日志」查看各终端输出。"
      />

      <Space direction="vertical" size={6} style={{ display: 'flex', marginBottom: 12 }}>
        <Text strong>推荐示例</Text>
        <Code>{`1. 进入测试目录
2. 终端A：执行命令：./nvsipl_camera -c cfg.json -m "0x0001"
3. 输入 gc 0

4. 终端B：执行命令：sudo ./fault_simulation_728.sh -i 7 -a 0x1a -n 5
5. 等待 5 秒
6. 终端A：输入 q`}</Code>
      </Space>

      <Collapse
        defaultActiveKey={['format', 'command', 'terminal']}
        items={sections.map((s) => ({
          key: s.key,
          label: s.label,
          children: s.children,
        }))}
      />
    </Modal>
  )
}
