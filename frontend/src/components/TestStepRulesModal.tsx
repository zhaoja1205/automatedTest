/**
 * 「测试步骤」编写规则说明弹窗。
 *
 * 内容与后端 CommandParser 的实际解析行为保持一致，
 * 帮助用例编写者写出能被正确识别为远端命令的步骤。
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
            • 每条步骤建议用 <Text code>1.</Text> <Text code>1、</Text> <Text code>1．</Text> 编号；
            没有编号时整段文本会被当作一步。
          </Item>
          <Item>
            • 一个编号对应一条主命令。同一步内需要执行多条命令时，可分行书写，
            每行以 <Text code>./</Text>、<Text code>sudo ./</Text>、<Text code>i2c...</Text>、
            <Text code>export</Text> 等命令开头，系统会拆成多条依次执行。
          </Item>
          <Item>
            • 行内的 <Text code>①②③</Text> 注释以及 <Text code>注：</Text> 之后的内容不会执行，可用于补充说明。
          </Item>
          <Item>
            • 中英文冒号（<Text code>:</Text> / <Text code>：</Text>）都可以；中文引号会自动转换为英文引号。
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
            支持的前缀：<Text code>执行命令：</Text> <Text code>需执行的命令：</Text>
            <Text code>所执行命令：</Text> <Text code>指令：</Text> <Text code>起流：</Text>
            <Text code>测试指令：</Text> <Text code>命令：</Text> <Text code>输入命令：</Text>
            <Text code>故障注入：</Text>
          </Item>
          <Item><Text strong>不带前缀时，仅以下形式能直接识别</Text></Item>
          <Code>{`1. ./run_test.sh --case 1
2. sudo ./run_test.sh --case 1
3. nvsipl_camera -c cfg.json -m "0x0001" -r 5
4. i2cmastercmd -w 0x1a 0x10 0x01
5. cd /root/test
6. scp /root/a.bin root@192.168.1.2:/tmp/
7. devopen /dev/video0
8. export CAM_ROTATE_CFG_PATH=/root/cfg.json
9. \`ls -l /root\``}</Code>
          <Item>
            <Text type="warning">注意：</Text><Text code>ls</Text>、<Text code>echo</Text>、
            <Text code>cat</Text>、<Text code>mkdir</Text>、<Text code>sudo chmod</Text>、
            <Text code>i2ctransfer</Text> 等裸命令<Text strong>不会</Text>自动识别，
            请加前缀写成 <Text code>执行命令：ls -l /root</Text>。
          </Item>
          <Item>
            • <Text code>另一个终端执行：命令</Text> 可标记为另一个终端；建议使用冒号形式，
            不要用引号包裹，避免多余的引号被带入命令。
          </Item>
          <Item>
            • <Text code>export VAR=value</Text>、<Text code>source /path/env.sh</Text> 会被识别为
            shell 内置命令；当同时存在 export、重复步骤和起流命令时，自动启用「持久化 Shell」，
            环境变量在整个会话内有效。
          </Item>
          <Item>
            <Text type="warning">注意：</Text>隐式写法要求命令中包含可执行关键字，
            否则会被当作说明文字跳过。拿不准时加「执行命令：」前缀。
          </Item>
        </>
      ),
    },
    {
      key: 'dir',
      label: '3. 目录与前置条件',
      children: (
        <>
          <Item><Text strong>切换远端工作目录</Text></Item>
          <Code>{`1. 进入测试目录
2. 进入目录 /opt/camera/test
3. cd /root/nvsipl_test`}</Code>
          <Item>
            • 「进入测试目录 / 进入调试目录 / 进入目录 / 进入工作目录」会切换工作目录：
            优先使用「工作区配置 → 默认远端路径」，未配置时取步骤文本中的绝对路径。
          </Item>
          <Item>• 切换后，后续命令会以 <Text code>cd &lt;目录&gt; &amp;&amp; &lt;命令&gt;</Text> 的形式下发。</Item>

          <Item><Text strong>前置条件字段</Text></Item>
          <Code>{`echo ready; insmod /root/camera.ko; MANUAL_CONFIRM 确认板端已上电`}</Code>
          <Item>
            • 多条前置命令用英文分号 <Text code>;</Text> 分隔，原样下发，且不经过测试步骤的命令解析。
          </Item>
          <Item>
            • <Text code>MANUAL_CONFIRM 说明文字</Text> 会弹出人工确认框；任一条命令返回码非 0 时，
            该用例直接判 Fail，测试步骤不再执行。
          </Item>
        </>
      ),
    },
    {
      key: 'nvsipl',
      label: '4. nvsipl 交互命令',
      children: (
        <>
          <Code>{`1. 执行命令：./nvsipl_camera -c cfg.json -m "0x0001" -r 5
2. 输入 gc 0
3. 输入 'ro'
4. 执行 dl 0, dl 2, el 3
5. 输入 q`}</Code>
          <Item>
            • 支持写法：<Text code>输入 gc</Text>、<Text code>输入 gc 0</Text>、
            <Text code>输入 'ro'</Text>、<Text code>执行 dl 0, el 11</Text>、
            <Text code>发送 al</Text>。
          </Item>
          <Item>
            • 支持的子命令：<Text code>gc</Text> <Text code>dl</Text> <Text code>dlo</Text>
            <Text code>el</Text> <Text code>elr</Text> <Text code>ro</Text> <Text code>al</Text>
            <Text code>ed</Text> <Text code>th</Text> <Text code>df</Text> <Text code>bp</Text>
            <Text code>sr</Text> <Text code>hs</Text> <Text code>ex</Text> <Text code>q</Text>。
          </Item>
          <Item>
            • 起流命令带 <Text code>-r N</Text>（N 秒后自动退出）时，后续交互输入会合并成管道命令一次下发，
            并在组间自动插入等待；不带 <Text code>-r</Text> 的阻塞型起流会占用 PTY，交互命令逐条发送，
            <Text code>q</Text> 用于退出。
          </Item>
          <Item>
            • 系统<Text strong>不会自动注入 gc</Text>；只有步骤里显式写了
            <Text code>输入 gc</Text>、<Text code>输入 gc 0</Text> 等，才会发送 gc 命令。
          </Item>
        </>
      ),
    },
    {
      key: 'repeat',
      label: '5. 重复与压力测试',
      children: (
        <>
          <Code>{`1. 执行命令：./nvsipl_camera -c cfg.json -m "0x0001" -r 5
2. 输入 dl 0, dl 2
3. 重复1-2
4. 重复步骤2

5. 执行命令：./nvsipl_camera -c cfg.json -m "0x0001"
6. 反复起流10次`}</Code>
          <Item>
            • 重复范围：<Text code>重复1-3</Text>、<Text code>重复1-3步骤</Text>、
            <Text code>重复第1~3步</Text>；单步：<Text code>重复步骤1</Text>。
          </Item>
          <Item>
            • 反复起流：<Text code>反复起流10次</Text>、<Text code>重复起流5次</Text>，
            每轮执行 起流 → 按步骤显式写的交互命令（如 <Text code>输入 gc N</Text>）→
            检测帧率 → q 退出。未写 gc 时不会自动注入。
          </Item>
          <Item>
            <Text type="warning">注意：</Text>重复指令只有在「持久化 Shell 模式」（同时含 export、重复、起流）
            或「并行故障模式」（阻塞型起流后还有步骤）下才会展开；普通顺序执行中会被忽略。
          </Item>
          <Item>
            • 步骤序号从 1 开始，指解析后的步骤顺序；建议重复范围只包含命令步骤。
          </Item>
        </>
      ),
    },
    {
      key: 'manual',
      label: '6. 人工操作与人工确认',
      children: (
        <>
          <Code>{`1. 手动切换 Camera 通道
2. 人为手动拔插 camera 线缆
3. MANUAL_CONFIRM 检查屏幕是否有显示异常`}</Code>
          <Item>
            • 含「人为手动、手动切换、手动操作、手动拔、手动插、人工操作、人工切换、人为操作、
            物理操作、拔插、插拔」的步骤会被标记为人工操作，<Text strong>不会自动下发</Text>，只提示操作人员。
          </Item>
          <Item>
            • <Text code>MANUAL_CONFIRM</Text> 必须写在步骤开头，执行到此步骤时前端弹出「确认 Pass / 确认 Fail」；
            选择 Fail 时该用例判 Fail 并停止后续步骤。
          </Item>
        </>
      ),
    },
    {
      key: 'skip',
      label: '7. 会被跳过的内容与 NA',
      children: (
        <>
          <Item>• <Text code>ssh ...</Text> 连接命令：由系统管理连接，步骤中的 ssh 命令会跳过。</Item>
          <Item>
            • 以 <Text code>注：</Text> <Text code>注意：</Text> <Text code>备注：</Text>
            <Text code>说明：</Text> <Text code>Note:</Text> 或 <Text code>①</Text> 开头的步骤视为注释。
          </Item>
          <Item>
            • 纯英文说明（无中文、长度 ≥ 10 且没有可执行命令），以及「查看 / 打开 / 确认 / 验证 / 检查」
            等描述性文字且不含命令的步骤，会被跳过。
          </Item>
          <Item>
            • 无法识别的步骤会被标记为「未识别步骤（已跳过）」，不影响执行，但也不会下发命令；
            可点击行内 <Tag color="purple">AI</Tag> 按钮解析后再预览。
          </Item>
          <Item>
            • 用例任意字段出现 <Text code>待写入</Text> <Text code>待补充</Text> <Text code>待完善</Text>
            <Text code>暂不测试</Text> <Text code>不适用</Text> <Text code>TBD</Text>
            <Text code>N/A</Text> <Text code>TODO</Text> 或单独的 <Text code>NA</Text> 时，
            整条用例自动标记为 NA，不执行。
          </Item>
        </>
      ),
    },
    {
      key: 'ai',
      label: '8. AI 兜底解析',
      children: (
        <>
          <Item>
            • 只有在规则解析出现「未识别步骤」时，AI 才会参与；AI 不会改写已被规则识别的步骤。
          </Item>
          <Item>
            • 点击「测试步骤」列内的 <Tag color="purple">AI</Tag> 按钮可单条解析，或使用工具栏的批量解析。
            置信度 ≥ 0.6 的 AI 结果才会替换未识别步骤，低于 0.6 仅作为建议显示。
          </Item>
          <Item>
            • 解析结果会缓存在当前会话中，执行和「查看执行命令」都会复用。
          </Item>
        </>
      ),
    },
    {
      key: 'faq',
      label: '9. 常见问题',
      children: (
        <>
          <Item>
            <Text strong>Q：命令没被执行？</Text>
            <br />
            先点该行的命令预览按钮，确认步骤是否被识别。若显示「未识别步骤」，改用
            <Text code>执行命令：命令</Text> 的显式写法或使用 AI 解析。
          </Item>
          <Item>
            <Text strong>Q：-r 和 -R 有什么区别？</Text>
            <br />
            小写 <Text code>-r N</Text> 表示运行 N 秒后自动退出，属于非阻塞起流；
            <Text code>-R</Text> 是功能参数，不控制退出。需要人工/脚本交互的用例应使用不带 <Text code>-r</Text> 的阻塞模式。
          </Item>
          <Item>
            <Text strong>Q：多条命令能写在同一行吗？</Text>
            <br />
            可以用 <Text code>;</Text> 连接，但它会被当作一条 shell 命令行执行，出错时难以定位。
            建议拆成多个编号步骤。
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
        message="系统会把「测试步骤」逐条解析成远端命令；写法越规范，识别越准确。"
        description="编写完成后，点击用例行的命令图标可以预览最终下发到板端的完整命令。"
      />

      <Space direction="vertical" size={6} style={{ display: 'flex', marginBottom: 12 }}>
        <Text strong>推荐示例</Text>
        <Code>{`1. 进入测试目录
2. 执行命令：./nvsipl_camera -c cfg.json -m "0x0001" -r 5
3. 输入 gc 0
4. 另一个终端执行：sudo ./fault_simulation_728.sh -i 7 -a 0x1a -n 5
5. 输入 q`}</Code>
      </Space>

      <Collapse
        defaultActiveKey={['format', 'command']}
        items={sections.map((s) => ({
          key: s.key,
          label: s.label,
          children: s.children,
        }))}
      />
    </Modal>
  )
}
