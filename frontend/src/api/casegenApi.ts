/**
 * 生成测试用例模块 API。
 */
import api from './axios'
import type { PlatformConfigParseResult } from '../types/casegen'

/** 读取并解析平台配置文件（predev_mixgroup_platform.json） */
export const parsePlatformConfig = (path: string) =>
  api.post<PlatformConfigParseResult>(
    '/casegen/platform-config/parse',
    { path },
    { timeout: 30000 },
  )
