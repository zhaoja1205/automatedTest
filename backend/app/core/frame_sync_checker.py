"""帧同步检测器 — 解析 nvsipl_camera --showmetadata 输出并计算 SOF 同步精度。

当 nvsipl_camera 启动参数含 --showmetadata 时，gc 出帧后会输出每个 camera 的
TSC SOF 时间戳。本模块负责：
1. 解析 metadata 输出，提取 (camera_id, sof) 序列（自动去重）
2. 自适应检测 SOF 单位（ns 或 ticks×32）
3. 按 SOF 值接近度进行时间片分组（同一帧的所有 camera）
4. 计算每片内 SOF max-min 差值，转 ms 后与阈值比较
5. 从预期结果自然语言中提取判定参数（阈值）
"""
import re
from typing import Dict, List, Optional, Tuple


class FrameSyncChecker:
    """帧同步检测器。"""

    @staticmethod
    def is_frame_sync_case(nvsipl_cmd: str) -> bool:
        """判断 nvsipl_camera 命令是否含 --showmetadata 参数。"""
        if not nvsipl_cmd:
            return False
        return '--showmetadata' in nvsipl_cmd.lower() or '--showmetadata' in nvsipl_cmd

    @staticmethod
    def parse_sync_criteria(expected_text: str) -> Dict:
        """从预期结果文本提取帧同步判定参数。

        Returns:
            {
                'threshold_ms': float,  # 阈值（毫秒）
            }
        """
        if not expected_text:
            return {'threshold_ms': 5.0}

        # 提取阈值: < 5ms / ＜5ms / 小于5ms / 不超过5ms
        threshold_ms = 5.0  # 默认
        patterns = [
            r'[<＜]\s*(\d+(?:\.\d+)?)\s*ms',
            r'小于\s*(\d+(?:\.\d+)?)\s*ms',
            r'不超过\s*(\d+(?:\.\d+)?)\s*ms',
            r'误差[^0-9]*(\d+(?:\.\d+)?)\s*ms',
        ]
        for pat in patterns:
            m = re.search(pat, expected_text)
            if m:
                threshold_ms = float(m.group(1))
                break

        return {
            'threshold_ms': threshold_ms,
        }

    @staticmethod
    def parse_metadata_output(output: str) -> List[Tuple[int, int]]:
        """解析 metadata 输出为 (camera_id, sof) 序列（自动去重连续相同记录）。

        每条 metadata 记录格式：
            Camera ID: 12
             TSC SOF: 100452954823088

        nvsipl 的 --showmetadata 模式下每个 camera 每帧会输出两次（Out0/Out1），
        SOF 值相同。本方法自动合并连续相同的 (camera_id, sof) 对。

        Returns:
            [(camera_id, sof), ...] 去重后按出现顺序
        """
        records = []
        lines = output.split('\n')
        current_camera_id = None
        last_record = None  # 用于去重

        for line in lines:
            # 匹配 Camera ID
            cam_match = re.search(r'Camera\s+ID:\s*(\d+)', line)
            if cam_match:
                current_camera_id = int(cam_match.group(1))
                continue

            # 匹配 TSC SOF（必须在一个 Camera ID 之后）
            if current_camera_id is not None:
                sof_match = re.search(r'TSC\s+SOF:\s*(\d+)', line)
                if sof_match:
                    sof_value = int(sof_match.group(1))
                    record = (current_camera_id, sof_value)
                    # 去重：跳过与上一条完全相同的 (camera_id, sof)
                    if record != last_record:
                        records.append(record)
                        last_record = record
                    current_camera_id = None  # 重置，等下一个 Camera ID

        return records

    @staticmethod
    def detect_sof_unit(records: List[Tuple[int, int]]) -> str:
        """自适应检测 SOF 单位。

        通过计算同一 camera 的相邻帧间隔来判断 SOF 是纳秒还是 ticks。
        - 30fps → 帧间隔 33.33ms
        - 如果帧间隔 ~33_000_000 → SOF 单位是 ns（TSC 1GHz）
        - 如果帧间隔 ~1_000_000 → SOF 单位是 ticks（TSC 31.25MHz，×32 = ns）

        Returns:
            'ns' — SOF 直接就是纳秒
            'ticks' — SOF 需要 ×32 转为纳秒
        """
        # 收集每个 camera 的 SOF 序列
        cam_sofs: Dict[int, List[int]] = {}
        for cam_id, sof in records:
            if cam_id not in cam_sofs:
                cam_sofs[cam_id] = []
            cam_sofs[cam_id].append(sof)

        # 计算帧间隔
        intervals = []
        for cam_id, sofs in cam_sofs.items():
            if len(sofs) < 2:
                continue
            for i in range(1, min(len(sofs), 10)):  # 取前几帧
                interval = sofs[i] - sofs[i - 1]
                if interval > 0:
                    intervals.append(interval)

        if not intervals:
            return 'ticks'  # 无法判断，默认需要 ×32

        # 取中位数
        intervals.sort()
        median_interval = intervals[len(intervals) // 2]

        # 30fps 帧间隔:
        #   ns 模式: ~33_333_333 (33ms)
        #   ticks 模式 (31.25MHz): ~1_041_666 (1M ticks)
        # 判断边界: 10_000_000
        if median_interval > 10_000_000:
            return 'ns'
        else:
            return 'ticks'

    @staticmethod
    def group_timeslices_by_proximity(records: List[Tuple[int, int]], sof_unit: str) -> List[Dict[int, int]]:
        """按 SOF 值接近度分组时间片。

        同一帧的所有 camera SOF 应该非常接近（同组内 <1ms，跨组 <5ms）。
        不同帧之间间隔约 33ms（30fps）。

        分组策略：
        1. 确定帧间隔阈值（0.5 × 理论帧间隔）
        2. 按 SOF 值排序后，连续 SOF 差值 > 阈值则分片

        Args:
            records: (camera_id, sof) 序列
            sof_unit: 'ns' 或 'ticks'

        Returns:
            [{camera_id: sof, ...}, ...]  每个 dict 是一个时间片
        """
        if not records:
            return []

        # 帧间隔阈值：取理论帧间隔的一半作为分片阈值
        # 30fps → 33.33ms → 阈值取 ~16ms
        if sof_unit == 'ns':
            # SOF 单位是 ns，16ms = 16_000_000 ns
            split_threshold = 16_000_000
        else:
            # SOF 单位是 ticks (31.25MHz)，16ms = 500_000 ticks
            split_threshold = 500_000

        # 按 SOF 值排序
        sorted_records = sorted(records, key=lambda x: x[1])

        # 分片：连续 SOF 差值大于阈值则开始新片
        slices = []
        current: Dict[int, int] = {}
        prev_sof = sorted_records[0][1]

        for cam_id, sof in sorted_records:
            if current and (sof - prev_sof) > split_threshold:
                # 差值太大，开始新片
                slices.append(current)
                current = {}
            # 同一片内同一 camera 取最新值
            current[cam_id] = sof
            prev_sof = sof

        if current:
            slices.append(current)

        return slices

    @classmethod
    def check(cls, output: str, expected_text: str, nvsipl_cmd: str = "") -> Tuple[bool, str]:
        """帧同步检测主入口。

        Args:
            output: nvsipl_camera 含 --showmetadata 的完整输出
            expected_text: 用例预期结果文本
            nvsipl_cmd: 原始 nvsipl 命令（用于提取 sensor mask 等信息）

        Returns:
            (passed: bool, reason: str)
        """
        # 1. 解析判定参数
        criteria = cls.parse_sync_criteria(expected_text)
        threshold_ms = criteria['threshold_ms']

        # 2. 解析 metadata 输出（自动去重）
        records = cls.parse_metadata_output(output)
        if not records:
            return False, (
                f"帧同步检测: FAIL (未检测到 metadata 输出，"
                f"请确认命令含 --showmetadata 且成功出帧)"
            )

        # 3. 自适应检测 SOF 单位
        sof_unit = cls.detect_sof_unit(records)

        # 4. 按 SOF 值接近度分组
        slices = cls.group_timeslices_by_proximity(records, sof_unit)
        if not slices:
            return False, "帧同步检测: FAIL (无法分组时间片)"

        # 过滤掉不完整的时间片（camera 数量少于 2）
        valid_slices = [s for s in slices if len(s) >= 2]
        if not valid_slices:
            return False, (
                f"帧同步检测: FAIL (无有效时间片，"
                f"共解析到 {len(records)} 条记录、{len(slices)} 片，"
                f"但无片含 ≥2 个不同 camera)"
            )

        # 丢弃第一片（可能不完整/不稳定）和最后一片
        if len(valid_slices) > 2:
            analyze_slices = valid_slices[1:-1]
        else:
            analyze_slices = valid_slices

        # 5. 计算每片的同步精度
        all_diffs_ms = []
        fail_details = []
        camera_ids_seen = set()
        debug_slices = []  # 前几片的详细数据

        for i, slice_data in enumerate(analyze_slices):
            sof_values = list(slice_data.values())
            max_sof = max(sof_values)
            min_sof = min(sof_values)
            diff_raw = max_sof - min_sof

            # 转换为 ms
            if sof_unit == 'ns':
                diff_ms = diff_raw / 1_000_000
            else:
                diff_ms = (diff_raw * 32) / 1_000_000

            all_diffs_ms.append(diff_ms)
            camera_ids_seen.update(slice_data.keys())

            # 收集前 5 片的详细数据用于调试
            if i < 5:
                max_cam = [k for k, v in slice_data.items() if v == max_sof][0]
                min_cam = [k for k, v in slice_data.items() if v == min_sof][0]
                debug_slices.append(
                    f"片{i+1}[{len(slice_data)}cam]: "
                    f"max=Camera{max_cam}({max_sof}) "
                    f"min=Camera{min_cam}({min_sof}) "
                    f"diff={diff_ms:.4f}ms"
                )

            if diff_ms >= threshold_ms:
                # 找出 max 和 min 对应的 camera
                max_cam = [k for k, v in slice_data.items() if v == max_sof][0]
                min_cam = [k for k, v in slice_data.items() if v == min_sof][0]
                fail_details.append(
                    f"第{i+1}片: {diff_ms:.3f}ms "
                    f"(Camera {max_cam} - Camera {min_cam})"
                )

        # 6. 汇总结果
        avg_diff = sum(all_diffs_ms) / len(all_diffs_ms) if all_diffs_ms else 0
        max_diff = max(all_diffs_ms) if all_diffs_ms else 0
        total_slices = len(analyze_slices)
        fail_count = len(fail_details)
        camera_list = sorted(camera_ids_seen)

        unit_desc = "SOF(ns)" if sof_unit == 'ns' else "SOF×32(ns)"
        camera_str = "/".join(str(c) for c in camera_list)
        debug_info = " | ".join(debug_slices[:3])

        if fail_count == 0:
            # 全部通过
            reason = (
                f"帧同步检测: PASS "
                f"({unit_desc}, 单位自检={sof_unit}, 阈值<{threshold_ms}ms, "
                f"{total_slices}片平均{avg_diff:.4f}ms, 最大{max_diff:.4f}ms, "
                f"Camera: {camera_str}; "
                f"采样: {debug_info})"
            )
            return True, reason
        else:
            # 有失败
            reason = (
                f"帧同步检测: FAIL "
                f"({unit_desc}, 单位自检={sof_unit}, 阈值<{threshold_ms}ms, "
                f"{total_slices}片中{fail_count}片超标, "
                f"最大差值{max_diff:.3f}ms; "
                f"超标详情: {'; '.join(fail_details[:3])}; "
                f"采样: {debug_info})"
            )
            return False, reason

    # ===== 嵌入行信息（metadata embedded line）人工确认支持 =====

    @staticmethod
    def is_metadata_embedded_case(expected_text: str) -> bool:
        """判断是否为嵌入行信息人工确认用例。

        当预期结果中提及曝光、增益、帧序号等 metadata 字段时，
        表示需要人工查看 log 比对，而非自动帧同步判定。
        """
        if not expected_text:
            return False
        keywords = [
            '嵌入行', '曝光时长', '曝光时间', '模拟增益', '数字增益', '帧序号',
            'embedded', 'exposure', 'analog gain', 'digital gain',
        ]
        text = expected_text
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    @staticmethod
    def is_sr_hs_review_case(expected_text: str) -> bool:
        """判断是否为 sr/hs 待确认用例。

        预期结果中提及 ROI 设置或直方图读取时，需人工核对 log。
        """
        if not expected_text:
            return False
        keywords = [
            'ROI', 'roi', '直方图', 'histogram', 'histogramInfo',
            'set ROI', '设置ROI', '读到直方图',
        ]
        text_lower = expected_text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    @staticmethod
    def extract_metadata_frames(output: str, max_frames: int = 10) -> str:
        """从 metadata 输出中截取指定帧数的完整记录（去重）。

        每帧格式示例：
            Camera ID: 0
             Frame Counter: 122592
             TSC SOF: 189253488155167
             TSC EOF: 189253517438038
             TSC temp: 73.6875
             exp0: 0.011000
             exp1: 0.011000
             exp2: 0.000028
             gain0: 15.848933
             gain1: 1.000000
             dgain: 1.000000
             wbGain2: {1.449219, 1.000000, 1.000000, 2.593750}

        去重规则：同一 Camera ID + 同一 Frame Counter 只保留一次。

        Returns:
            格式化的 metadata log 字符串（多帧），供人工确认展示。
        """
        lines = output.split('\n')
        frames = []  # [(camera_id, frame_counter, [lines...])]
        current_camera = None
        current_frame_counter = None
        current_lines = []
        seen_keys = set()  # (camera_id, frame_counter) 去重

        for line in lines:
            # 匹配 Camera ID 开始新记录
            cam_match = re.search(r'Camera\s+ID:\s*(\d+)', line)
            if cam_match:
                # 保存上一条记录
                if current_camera is not None and current_frame_counter is not None:
                    key = (current_camera, current_frame_counter)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        frames.append((current_camera, current_frame_counter, current_lines))
                # 开始新记录
                current_camera = int(cam_match.group(1))
                current_frame_counter = None
                current_lines = [line.rstrip()]
                continue

            if current_camera is not None:
                stripped = line.strip()
                if not stripped:
                    continue
                # 跳过非 metadata 行（菜单、fps 等），但不截断当前记录
                # PTY 缓冲区可能导致 Frame rate / 菜单行穿插在 metadata 行之间
                if stripped.startswith("Enter '") or 'Frame rate' in stripped:
                    continue
                if stripped in ('-', 'Output'):
                    continue

                current_lines.append(line.rstrip())

                # 提取 Frame Counter
                fc_match = re.search(r'Frame Counter:\s*(\d+)', stripped)
                if fc_match:
                    current_frame_counter = int(fc_match.group(1))

        # 保存最后一条记录
        if current_camera is not None and current_frame_counter is not None:
            key = (current_camera, current_frame_counter)
            if key not in seen_keys:
                frames.append((current_camera, current_frame_counter, current_lines))

        if not frames:
            return "(未检测到有效 metadata 帧记录)"

        # 取前 max_frames 帧
        selected = frames[:max_frames]
        result_lines = []
        for i, (cam_id, fc, frame_lines) in enumerate(selected):
            if i > 0:
                result_lines.append("")  # 帧间空行
            result_lines.extend(frame_lines)

        # 追加统计信息
        all_cameras = sorted(set(f[0] for f in frames))
        all_frame_counters = sorted(set(f[1] for f in frames))
        result_lines.append("")
        result_lines.append(
            f"--- 共检测到 {len(frames)} 帧记录 (去重后), "
            f"Camera: {all_cameras}, "
            f"Frame Counter 范围: {all_frame_counters[0]}~{all_frame_counters[-1]} ---"
        )

        return "\n".join(result_lines)
